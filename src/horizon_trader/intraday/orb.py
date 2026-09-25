"""Opening Range Breakout on Stocks in Play (Zarattini, Barbon & Aziz 2024, SSRN 4729284).

    uv run python -m horizon_trader.intraday.orb [--rebuild] [--minutes 5]

Paper rules (defaults, not tuned), applied to every US common stock incl. delisted ones:
  filters  open > $5, 14-day avg volume >= 1M shares, 14-day ATR > $0.50
  select   relative volume of the first n minutes >= 1, top 20 by relative volume
  side     long if the n-minute candle closed up, short if down, skip if flat
  entry    stop order at the opening-range high (long) / low (short)
  stop     10% of ATR from the entry fill; otherwise exit at the close
  sizing   1% of equity lost if stopped, at most 4x leverage (split evenly across the top N)

Simulation choices the paper doesn't spell out:
  - Minute bars can't say whether the entry or the stop came first inside the entry minute,
    and with a stop of 0.1 ATR (median 14 cents) that decides the result: about half of all
    trades touch the stop inside the entry minute. Exits are computed three ways (see
    simulate_trade); "path" is the usual OHLC-order guess and the default.
  - A gap through a level fills at the bar's open (entry or stop), not at the level.
  - Close exits fill at the official close (a market-on-close order), without slippage.
    Slippage is charged per share on stop fills (every entry, and stop-outs).
  - Short borrow cost isn't modeled. Shorts under the short-sale restriction (stock down 10%
    from yesterday's close before entry) are flagged and reported separately.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import date

import numpy as np
import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.config import data_dir
from horizon_trader.data import massive, massive_ref
from horizon_trader.execution.costs import FINRA_TAF, IBKR_PLANS, SEC_FEE, CostModel
from horizon_trader.intraday import features as F

CLOSE_TIME = pd.Timedelta(hours=6, minutes=30)  # 9:30 + 6h30 = 16:00


@dataclass(frozen=True)
class OrbRules:
    minutes: int = 5
    lookback: int = 14
    min_price: float = 5.0
    min_avg_volume: float = 1_000_000
    min_atr: float = 0.50
    min_relvol: float = 1.0
    stop_atr: float = 0.10
    keep: int = 50  # candidates simulated per day; portfolios take the top N of these


RULES = OrbRules()


# ---------------------------------------------------------------- selection and simulation


def select_candidates(day: pd.DataFrame, rules: OrbRules = RULES) -> pd.DataFrame:
    """Rank one day's tickers (index) by relative volume after the paper's filters.

    `day` needs columns open, atr, avg_volume, relvol, or_open, or_close, opens_on_time.
    """
    ok = (
        day["opens_on_time"].fillna(False).astype(bool)
        & (day["open"] > rules.min_price)
        & (day["avg_volume"] >= rules.min_avg_volume)
        & (day["atr"] > rules.min_atr)
        & (day["relvol"] >= rules.min_relvol)
        & (day["or_close"] != day["or_open"])
    )
    c = day[ok].sort_index().sort_values("relvol", ascending=False, kind="stable").head(rules.keep)
    c = c.assign(side=np.sign(c["or_close"] - c["or_open"]).astype(int))
    return c.assign(rank=np.arange(1, len(c) + 1))


MODES = ("cons", "path", "opt")


def simulate_trade(
    o: np.ndarray,
    h: np.ndarray,
    low: np.ndarray,
    c: np.ndarray,
    side: int,
    level: float,
    stop_dist: float,
    close_px: float,
) -> dict | None:
    """One stop-entry trade on the bars after the opening range. None if never triggered.

    A minute bar doesn't say whether the stop was touched before or after the entry inside
    the entry minute, so the exit is computed three ways (exit index len(o) = the close):
      cons  any touch of the stop in the entry minute counts (pessimistic)
      path  assume up-bars go open-low-high-close and down-bars open-high-low-close
      opt   the stop is only checked from the next minute. Not an upper bound: a skipped
            stop often gaps through on the next open and loses several R instead of one.
    """
    hits = np.flatnonzero(h >= level) if side > 0 else np.flatnonzero(low <= level)
    if not len(hits):
        return None
    k = int(hits[0])
    fill = max(level, o[k]) if side > 0 else min(level, o[k])
    stop = fill - side * stop_dist
    adverse = low if side > 0 else h

    def breached(x):
        return x <= stop if side > 0 else x >= stop

    later = np.flatnonzero(breached(adverse[k + 1 :]))
    gapped = o[k] >= level if side > 0 else o[k] <= level
    with_trend = c[k] >= o[k] if side > 0 else c[k] <= o[k]
    # path: in a bar moving our way, the adverse extreme came before the level was crossed,
    # so only a close back through the stop counts; otherwise the adverse extreme came after
    in_entry_bar = {
        "cons": bool(breached(adverse[k])),
        "path": bool(breached(c[k]) if with_trend and not gapped else breached(adverse[k])),
        "opt": False,
    }
    out = {"entry_idx": k, "entry_px": fill, "stop_px": stop}
    for mode, stopped_now in in_entry_bar.items():
        if stopped_now:
            px, j = stop, k
        elif len(later):
            j = k + 1 + int(later[0])
            px = min(o[j], stop) if side > 0 else max(o[j], stop)  # a gap fills at the open
        else:
            px, j = close_px, len(o)
        out |= {f"exit_px_{mode}": px, f"exit_idx_{mode}": j, f"stopped_{mode}": j < len(o)}
    return out


def simulate_day(
    session: pd.DataFrame, cands: pd.DataFrame, day: date, rules: OrbRules = RULES
) -> pd.DataFrame:
    """Every candidate's trade (or non-trade) on one day. `session` = that day's 9:30-16:00 bars."""
    start = F.session_open(day)
    after_or = start + pd.Timedelta(minutes=rules.minutes)
    by_ticker = dict(tuple(session.groupby("ticker", sort=False)))
    rows = []
    for tk, c in cands.iterrows():
        bars = by_ticker.get(tk)
        row = {"date": pd.Timestamp(day), "ticker": tk, "triggered": False}
        row |= {k: c[k] for k in ("rank", "relvol", "side", "atr", "open", "prev_close", "close")}
        level = c["or_high"] if c["side"] > 0 else c["or_low"]
        stop_dist = rules.stop_atr * c["atr"]
        row |= {"level": level, "stop_dist": stop_dist}
        if bars is not None:
            post = bars[bars["ts"] >= after_or]
            o, h, lo, cl = (post[f].to_numpy(float) for f in ("open", "high", "low", "close"))
            res = simulate_trade(o, h, lo, cl, int(c["side"]), level, stop_dist, c["close"])
            if res is not None:
                k = res["entry_idx"]
                low_so_far = bars.loc[bars["ts"] <= post["ts"].iloc[k], "low"].min()
                row |= res | {"triggered": True, "entry_time": post["ts"].iloc[k]}
                row["ssr"] = c["side"] < 0 and low_so_far <= 0.9 * c["prev_close"]
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- building the trade table


def _derived(name: str) -> pd.DataFrame | None:
    path = data_dir() / "massive" / "derived" / f"{name}.parquet"
    return pd.read_parquet(path) if path.exists() else None


def _save(df: pd.DataFrame, name: str) -> None:
    path = data_dir() / "massive" / "derived" / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


OR_COLS = ["or_open", "or_high", "or_low", "or_close", "or_volume", "opens_on_time"]


def opening_ranges(
    days: list[date], tickers: set[str], minutes: int, rebuild: bool = False
) -> pd.DataFrame:
    """Opening range of every ticker on every day, cached (long format)."""
    name = f"or{minutes}"
    cached = None if rebuild else _derived(name)
    have = set() if cached is None else set(cached["date"].dt.date)
    new = []
    for i, d in enumerate(x for x in days if x not in have):
        start = F.session_open(d)
        window = [("ts", ">=", start), ("ts", "<", start + pd.Timedelta(minutes=minutes))]
        bars = pd.read_parquet(massive.local_path("minute", d), filters=window)
        new.append(F.opening_range(bars, d, minutes).reset_index().assign(date=pd.Timestamp(d)))
        if (i + 1) % 100 == 0:
            print(f"  opening ranges: {i + 1} new days", flush=True)
    if new:
        cached = pd.concat([cached, *new] if cached is not None else new, ignore_index=True)
        _save(cached, name)
    out = cached[cached["ticker"].isin(tickers) & cached["date"].dt.date.isin(set(days))]
    return out


def build_trades(rules: OrbRules = RULES, rebuild: bool = False) -> pd.DataFrame:
    """Candidates and simulated trades for every day with minute data (cached)."""
    name = f"orb{rules.minutes}_stop{rules.stop_atr:g}_trades"
    minute_days = massive.local_days("minute")
    day_days = massive.local_days("day")
    cached = None if rebuild else _derived(name)
    done = set() if cached is None else set(cached["date"].dt.date)

    common = massive_ref.load_common_tickers()
    panels = F.load_daily_panels(day_days, common)
    factor = F.split_factors(
        panels["open"].index, panels["open"].columns, massive_ref.load_splits()
    )
    feats = F.daily_features(panels, factor, rules.lookback)

    days = [d for d in minute_days if d in set(day_days)]
    ors = opening_ranges(days, common, rules.minutes, rebuild)
    wide = {c: ors.pivot(index="date", columns="ticker", values=c) for c in OR_COLS}
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    fac = factor.reindex(idx)
    traded = panels["volume"].reindex(idx).fillna(0) > 0
    relvol = F.relative_volume(wide["or_volume"], fac, traded, rules.lookback)

    new = []
    todo = [d for d in days if d not in done]
    for i, d in enumerate(todo):
        t = pd.Timestamp(d)
        day = pd.DataFrame({k: v.loc[t] for k, v in feats.items()})
        day = day.join(pd.DataFrame({k: v.loc[t] for k, v in wide.items()}), how="inner")
        day["relvol"] = relvol.loc[t]
        cands = select_candidates(day, rules)
        if cands.empty:
            continue
        start = F.session_open(d)
        window = [("ts", ">=", start), ("ts", "<", start + CLOSE_TIME)]
        filters = [("ticker", "in", list(cands.index)), *window]
        session = pd.read_parquet(massive.local_path("minute", d), filters=filters)
        new.append(simulate_day(session, cands, d, rules))
        if (i + 1) % 100 == 0:
            print(f"  simulated {i + 1}/{len(todo)} days", flush=True)
    if new:
        cached = pd.concat([cached, *new] if cached is not None else new, ignore_index=True)
        _save(cached, name)
    return cached.sort_values(["date", "rank"], ignore_index=True)


# ---------------------------------------------------------------- portfolio accounting

PLANS: dict[str, CostModel] = {
    "none": CostModel(per_share=0.0, min_per_order=0.0),
    "paper": CostModel(per_share=0.0035, min_per_order=0.0),  # what the paper charged
    **IBKR_PLANS,  # fixed / tiered, incl. pass-through and regulatory fees (execution/costs.py)
}
LITE = CostModel(per_share=0.0, min_per_order=0.0, sec_fee_rate=SEC_FEE, taf_per_share=FINRA_TAF)


@dataclass(frozen=True)
class Account:
    equity: float = 25_000.0
    top_n: int = 20
    risk: float = 0.01
    leverage: float = 4.0
    plan: str = "paper"
    slippage: float | None = (
        0.0  # $/share on every stop fill; None = per-trade entry_slip/exit_slip
    )
    same_bar: str = "path"


def trade_costs(qty, entry, exit_, side, plan: str, at_close=None) -> np.ndarray:
    """All-in cost (commission + pass-through + regulatory fees) of the entry and exit orders.

    "lite" (IBKR Lite, US residents only): $0 commission during regular hours, but close-auction
    (MOC) exits are only free while auction volume stays under 10% of the month's shares. ORB
    exits most trades at the close, so those pay the lesser of $0.005/share or 1% of value.
    """
    model = LITE if plan == "lite" else PLANS[plan]
    buy_first = np.asarray(side) > 0
    cost = np.array(
        [
            model.total(q if long else -q, a) + model.total(-q if long else q, b)
            for q, a, b, long in zip(qty, entry, exit_, buy_first, strict=True)
        ]
    )
    if plan == "lite":
        at_close = np.ones(len(qty), bool) if at_close is None else np.asarray(at_close, bool)
        cost += np.where(at_close, np.minimum(0.005 * qty, 0.01 * qty * exit_), 0.0)
    return cost


def run_portfolio(
    trades: pd.DataFrame, acct: Account, calendar: pd.DatetimeIndex | None = None
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily equity curve and per-trade fills. Positions are sized on start-of-day equity.

    `calendar` = every trading day of the test. Pass it whenever `trades` holds only the days
    that traded (e.g. filtered to triggered trades): a missing flat day would drop out of the
    equity curve and distort Sharpe and volatility.
    """
    days = calendar if calendar is not None else pd.DatetimeIndex(sorted(trades["date"].unique()))
    live = trades[(trades["rank"] <= acct.top_n) & trades["triggered"]]
    by_day = dict(tuple(live.groupby("date")))
    m = acct.same_bar
    equity, curve, fills = acct.equity, {}, []
    for d in days:
        t = by_day.get(d)
        if t is not None and equity > 0:
            side = t["side"].to_numpy()
            if acct.slippage is None:  # measured, per trade
                slip_in, slip_out = t["entry_slip"].to_numpy(), t["exit_slip"].to_numpy()
            else:
                slip_in = slip_out = acct.slippage
            entry = t["entry_px"].to_numpy() + side * slip_in
            stopped = t[f"stopped_{m}"].to_numpy(bool)
            exit_ = t[f"exit_px_{m}"].to_numpy() - side * slip_out * stopped
            cap = acct.leverage * equity / acct.top_n / entry
            qty = np.floor(np.minimum(acct.risk * equity / t["stop_dist"].to_numpy(), cap))
            ok = qty >= 1
            gross = side * qty * (exit_ - entry)
            q1 = np.maximum(qty, 1)
            costs = np.where(ok, trade_costs(q1, entry, exit_, side, acct.plan, ~stopped), 0)
            pnl = np.where(ok, gross - costs, 0.0)
            equity += pnl.sum()
            fills.append(
                t.assign(qty=qty, pnl=pnl, costs=costs, gross=np.where(ok, gross, 0)).assign(
                    entry_fill=entry, exit_fill=exit_, stopped=stopped
                )[ok]
            )
        curve[d] = equity
    curve = {days[0] - pd.Timedelta(days=1): acct.equity} | curve  # starting capital
    fills_df = pd.concat(fills, ignore_index=True) if fills else pd.DataFrame()
    return pd.Series(curve, name="equity"), fills_df


def r_multiple(trades: pd.DataFrame, mode: str = "cons") -> pd.Series:
    """Cost-free P&L per trade in units of the stop distance."""
    move = trades[f"exit_px_{mode}"] - trades["entry_px"]
    return trades["side"] * move / trades["stop_dist"]


# ---------------------------------------------------------------- results bundles


def bundle_trades(fills: pd.DataFrame, rules: OrbRules, mode: str = "path") -> pd.DataFrame:
    """run_portfolio fills -> bundle trade format, with exit times and MAE/MFE from minute bars.

    mae_R / mfe_R: the worst and best price reached between entry and exit, in R, at minute
    resolution (the entry minute's range before the fill is included, so both are slight
    overstatements).
    """
    out = []
    for day, g in fills.groupby("date"):
        start = F.session_open(day.date())
        after_or = start + pd.Timedelta(minutes=rules.minutes)
        tickers = sorted(set(g["ticker"]))
        window = [
            ("ts", ">=", after_or),
            ("ts", "<", start + CLOSE_TIME),
            ("ticker", "in", tickers),
        ]
        bars = pd.read_parquet(massive.local_path("minute", day.date()), filters=window)
        by_ticker = {tk: b.sort_values("ts") for tk, b in bars.groupby("ticker")}
        for _, r in g.iterrows():
            b = by_ticker[r.ticker]
            k, j = int(r.entry_idx), int(r[f"exit_idx_{mode}"])
            path = b.iloc[k : min(j, len(b) - 1) + 1]
            side, entry = int(r.side), r.entry_fill
            worst = path["low"].min() if side > 0 else path["high"].max()
            best = path["high"].max() if side > 0 else path["low"].min()
            out.append(
                {
                    "entry_time": r.entry_time,
                    "exit_time": b["ts"].iloc[j] if j < len(b) else start + CLOSE_TIME,
                    "symbol": r.ticker,
                    "side": side,
                    "qty": r.qty,
                    "entry_px": entry,
                    "exit_px": r.exit_fill,
                    "gross": r.gross,
                    "costs": r.costs,
                    "pnl": r.pnl,
                    "R": side * (r.exit_fill - entry) / r.stop_dist,
                    "exit_reason": "stop" if r.stopped else "close",
                    "stop_px": entry - side * r.stop_dist,
                    "mae_R": side * (entry - worst) / r.stop_dist,
                    "mfe_R": side * (best - entry) / r.stop_dist,
                    "rank": r["rank"],
                    "relvol": r.relvol,
                    "atr": r.atr,
                }
            )
    return pd.DataFrame(out)


ORB_CAVEATS = [
    "Minute bars: entry-minute stop touches resolved by the open-low-high-close guess (path).",
    "Short borrow cost not modeled; short-sale-restricted shorts are not excluded.",
    "Many variants (stop widths, top-N, order types, cost plans) were compared on this same "
    "data, so the best-looking setups are optimistic.",
]


def save_orb_run(
    name: str,
    trades: pd.DataFrame,
    acct: Account,
    rules: OrbRules,
    extra: dict | None = None,
    calendar: pd.DatetimeIndex | None = None,
) -> str:
    from horizon_trader.backtest.bundle import save_run

    equity, fills = run_portfolio(trades, acct, calendar)
    spy = benchmark(pd.DatetimeIndex(equity.index[1:]))
    meta = {
        "strategy": "ORB on Stocks in Play (Zarattini, Barbon & Aziz 2024)",
        "params": {"rules": rules.__dict__, "account": acct.__dict__},
        "oos_start": "2024-01-01",
        "chart": "massive_minute",
        "caveats": ORB_CAVEATS,
        "benchmark": "SPY (price only)",
    } | (extra or {})
    path = save_run(name, equity, bundle_trades(fills, rules, acct.same_bar), meta, spy)
    return path.name


# ---------------------------------------------------------------- report

PERIODS = {"all": (None, None), "2021-23": (None, "2023-12-31"), "2024+ (post-pub)": ("2024", None)}


def _slice(series: pd.Series, start: str | None, end: str | None) -> pd.Series:
    """Series within [start, end], keeping the last point before start as the base."""
    if end is not None:
        series = series[series.index <= pd.Timestamp(end)]
    if start is not None:
        i = series.index.searchsorted(pd.Timestamp(start))
        series = series.iloc[max(i - 1, 0) :]
    return series


def _stats(equity: pd.Series, fills: pd.DataFrame) -> dict:
    if len(equity) < 20:
        return {}
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    n = len(fills)
    return summarize(equity) | {
        "trades/yr": n / years,
        "hit": float((fills["pnl"] > 0).mean()) if n else np.nan,
        "$/trade": float(fills["pnl"].mean()) if n else np.nan,
        "costs/trade": float(fills["costs"].mean()) if n else np.nan,
    }


def _rows(label: str, trades: pd.DataFrame, acct: Account) -> list[dict]:
    """One row per period, each starting fresh with the account's capital."""
    rows = []
    for period, (a, b) in PERIODS.items():
        t = trades
        if a is not None:
            t = t[t["date"] >= pd.Timestamp(a)]
        if b is not None:
            t = t[t["date"] <= pd.Timestamp(b)]
        equity, fills = run_portfolio(t, acct)
        rows.append({"setup": label, "period": period} | _stats(equity, fills))
    return rows


def benchmark(days: pd.DatetimeIndex, ticker: str = "SPY") -> pd.Series:
    closes = {d: massive.load_day(d.date(), "day", [ticker])["close"] for d in days}
    return pd.Series({d: float(c.iloc[0]) for d, c in closes.items() if len(c)}, name=ticker)


def signal_report(trades: pd.DataFrame) -> str:
    """Cost-free trade quality in R (multiples of the stop distance), per same-bar convention."""
    t = trades[trades["triggered"]].copy()
    cols = [f"R_{m}" for m in MODES]
    for m in MODES:
        t[f"R_{m}"] = r_multiple(t, m)
    buckets = pd.cut(t["relvol"], [1, 2, 3, 5, 10, 30, np.inf], right=False)
    by_rv = t.groupby(buckets, observed=True)[cols].mean()
    by_rv["count"] = buckets.value_counts()
    by_side = t.groupby(t["side"].map({1: "long", -1: "short"}))[cols].mean()
    by_side.loc["short under SSR"] = t[t["ssr"].fillna(False).astype(bool)][cols].mean()
    years = t["date"].dt.year
    by_year = t.groupby(years)[cols].mean()
    by_year["count"] = years.value_counts()
    best = t["R_path"].sort_values(ascending=False)
    share = best.head(max(len(best) // 20, 1)).sum() / best.sum()
    ambiguous = (t["stopped_cons"] != t["stopped_opt"]).mean()
    return "\n".join(
        [
            f"candidates {len(trades):,}, triggered {len(t):,} ({len(t) / len(trades):.0%}); "
            f"entry minute ambiguous in {ambiguous:.0%} of trades",
            "avg R per trade, before costs:",
            t[cols].mean().round(3).to_frame("all").T.to_string(),
            by_side.round(3).to_string(header=False),
            f"best 5% of trades = {share:.0%} of total R (path)",
            "\nby relative volume:",
            by_rv.round(3).to_string(),
            "\nby year:",
            by_year.round(3).to_string(),
        ]
    )


def stop_sensitivity(stops: list[float], rules: OrbRules = RULES, rebuild: bool = False) -> str:
    """Same strategy at several stop widths. A robustness check, not a way to pick the best.

    R isn't comparable across widths (the unit changes), so trade quality is shown as
    "ATR/trade" = R x stop width, and money results use the same accounts throughout.
    """
    accounts = {
        "$25k top20 0c": Account(plan="fixed"),
        "$25k top20 1c": Account(plan="fixed", slippage=0.01),
        "$25k top20 2c": Account(plan="fixed", slippage=0.02),
        "$5k top2 1c": Account(equity=5_000.0, top_n=2, plan="fixed", slippage=0.01),
    }
    rows = []
    for stop in stops:
        trades = build_trades(replace(rules, stop_atr=stop), rebuild)
        t = trades[(trades["rank"] <= 20) & trades["triggered"]]
        row = {"stop (ATR)": stop, "median stop $": (t["stop_dist"]).median()}
        row["entry-min ambiguous"] = (
            t["stopped_cons"] & (t["exit_idx_cons"] == t["entry_idx"])
        ).mean()
        row["stopped out (path)"] = t["stopped_path"].mean()
        for m in MODES:
            row[f"ATR/trade {m}"] = (r_multiple(t, m) * stop).mean()
        for label, acct in accounts.items():
            s = _stats(*run_portfolio(trades, acct))
            row[f"{label} Sharpe"] = s.get("Sharpe", np.nan)
            if label.startswith("$5k"):
                row[f"{label} CAGR"], row[f"{label} maxDD"] = s.get("CAGR"), s.get("max DD")
        rows.append(row)
    with pd.option_context("display.width", 250, "display.max_columns", 50):
        return pd.DataFrame(rows).set_index("stop (ATR)").round(3).T.to_string()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--minutes", type=int, default=5)
    p.add_argument("--stop-atr", type=float, default=RULES.stop_atr)
    p.add_argument("--stops", help="comma-separated stop widths (in ATR) to compare, e.g. 0.1,0.5")
    p.add_argument("--rebuild", action="store_true", help="recompute the cached trade table")
    p.add_argument("--save", action="store_true", help="save headline runs for the dashboard")
    args = p.parse_args()

    rules = OrbRules(minutes=args.minutes, stop_atr=args.stop_atr)
    if args.stops:
        stops = [float(x) for x in args.stops.split(",")]
        print(stop_sensitivity(stops, rules, args.rebuild))
        return
    trades = build_trades(rules, rebuild=args.rebuild)
    first, last = trades["date"].min(), trades["date"].max()
    print(f"\n{args.minutes}-minute ORB, {first:%Y-%m-%d} .. {last:%Y-%m-%d}, top 20\n")
    print(signal_report(trades[trades["rank"] <= 20]) + "\n")

    paper = Account(plan="paper")
    setups = [(f"paper: $25k top20 paper-costs {m}", replace(paper, same_bar=m)) for m in MODES]
    setups += [
        ("$25k top20 fixed 0c", replace(paper, plan="fixed")),
        ("$25k top20 fixed 1c", replace(paper, plan="fixed", slippage=0.01)),
        ("$25k top20 fixed 2c", replace(paper, plan="fixed", slippage=0.02)),
        ("$25k top20 tiered 1c", replace(paper, plan="tiered", slippage=0.01)),
    ]
    mine = Account(equity=5_000.0, plan="fixed", slippage=0.01)
    for n in (1, 2, 5, 20):
        setups.append((f"$5k top{n} fixed 1c", replace(mine, top_n=n)))
        setups.append((f"$5k top{n} tiered 1c", replace(mine, top_n=n, plan="tiered")))
    rows = [r for label, acct in setups for r in _rows(label, trades, acct)]

    spy = benchmark(pd.DatetimeIndex(sorted(trades["date"].unique())))
    for per, (a, b) in PERIODS.items():
        bench = {"setup": "SPY buy & hold (price only)", "period": per}
        rows.append(bench | summarize(_slice(spy, a, b)))

    table = pd.DataFrame(rows).set_index(["setup", "period"])
    cols = ["CAGR", "Sharpe", "max DD", "trades/yr", "hit", "$/trade", "costs/trade", "final"]
    fmt = {c: "{:.1%}".format for c in ("CAGR", "max DD", "hit")}
    fmt |= {"Sharpe": "{:.2f}".format, "trades/yr": "{:,.0f}".format}
    fmt |= {c: "{:,.2f}".format for c in ("$/trade", "costs/trade")}
    fmt |= {"final": "{:,.0f}".format}
    if args.save:
        for label, acct in (setups[1], setups[4], ("$5k top1 fixed 1c", replace(mine, top_n=1))):
            print("saved", save_orb_run(f"ORB {rules.stop_atr:g}ATR {label}", trades, acct, rules))
    print("same-bar convention: path unless named; each period starts fresh")
    with pd.option_context("display.width", 200, "display.max_rows", 200):
        print(table.reindex(columns=cols).to_string(formatters=fmt, na_rep="-"))


if __name__ == "__main__":
    main()
