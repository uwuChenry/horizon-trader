"""Market intraday momentum on SPY: two published strategies at paper defaults, nothing tuned.

    uv run python -m horizon_trader.intraday.market_momentum [--ticker SPY] [--rebuild] [--save]

1. Noise-area breakout (Zarattini, Aziz & Barbon 2024, "Beat the Market", SSRN 4824172)
   band      sigma(t, m) = mean over the previous 14 days of |price at minute m / day open - 1|
             upper = max(open, prev close) * (1 + sigma)
             lower = min(open, prev close) * (1 - sigma)
   checks    HH:00 and HH:30 from 10:00 to 15:30, on the price at that time
   position  long above max(upper, VWAP), short below min(lower, VWAP), otherwise flat
             (VWAP is the paper's trailing stop); always flat at the close
   sizing    2% daily vol target on the previous 14 days' vol, at most 4x; same qty all day
   costs     paper: $0.0035/share commission + $0.001/share slippage

2. Last-half-hour momentum (Gao, Han, Li & Zhou 2018; Baltussen, Da, Lammers & Martens 2021)
   signal    sign of the return from yesterday's close to 30 minutes before today's close
             ("rod", Baltussen) or to 10:00 ("onfh", Gao)
   trade     enter 30 minutes before the close, exit at the close: one trade a day
   control   "long" = always long the last half hour, to separate the signal from plain drift

Simulation choices the papers don't pin down:
  - A signal uses the close of the minute ending at the check time; the fill is the next bar's
    open (the same instant in practice), plus slippage per share.
  - Close exits fill at the official close (market-on-close order) without slippage.
  - A reversal is charged as two orders (exit, then entry): conservative under a per-order minimum.
  - Prices are unadjusted, so SPY's quarterly ex-dividend gap slightly shifts the band that day.
  - Half days (13:00 close): checks stop at the close and the late window moves with it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from horizon_trader.backtest.metrics import summarize
from horizon_trader.config import data_dir
from horizon_trader.data import massive
from horizon_trader.execution.costs import IBKR_PLANS, CostModel
from horizon_trader.intraday import features as F

SESSION = 390  # minutes in a full session
CHECKS = tuple(range(29, 360, 30))  # price at 10:00, 10:30, ..., 15:30 = close of the bar before
LOOKBACK = 14
PUBLISHED = "2024-05-15"  # SSRN posting of the noise-area paper; its sample ends early 2024


# ---------------------------------------------------------------- data


def _derived_path(name: str):
    return data_dir() / "massive" / "derived" / f"{name}.parquet"


def load_bars(ticker: str = "SPY", rebuild: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(regular-session minute bars, daily bars) for one ticker from the Massive files, cached."""
    mpath, dpath = _derived_path(f"minute_{ticker}"), _derived_path(f"day_{ticker}")
    minute = pd.read_parquet(mpath) if mpath.exists() and not rebuild else None
    daily = pd.read_parquet(dpath) if dpath.exists() and not rebuild else None
    have = set() if daily is None else set(daily["date"].dt.date)
    day_files = set(massive.local_days("day"))
    todo = [d for d in massive.local_days("minute") if d in day_files and d not in have]
    new_m, new_d = [], []
    for i, d in enumerate(todo):
        start = F.session_open(d)
        window = [("ticker", "==", ticker), ("ts", ">=", start), ("ts", "<", start + CLOSE)]
        bars = pd.read_parquet(massive.local_path("minute", d), filters=window)
        new_m.append(bars.assign(date=pd.Timestamp(d)))
        new_d.append(massive.load_day(d, "day", [ticker]).assign(date=pd.Timestamp(d)))
        if (i + 1) % 200 == 0:
            print(f"  {ticker}: read {i + 1}/{len(todo)} days", flush=True)
    if new_m:
        minute = pd.concat([x for x in (minute, *new_m) if x is not None], ignore_index=True)
        daily = pd.concat([x for x in (daily, *new_d) if x is not None], ignore_index=True)
        mpath.parent.mkdir(parents=True, exist_ok=True)
        minute.to_parquet(mpath, index=False)
        daily.to_parquet(dpath, index=False)
    return minute, daily


CLOSE = pd.Timedelta(hours=6, minutes=30)


@dataclass
class Bars:
    """One ticker as day x minute-of-session matrices (column j = the bar starting 9:30 + j min).

    close     close of each bar, forward-filled over missing minutes up to the session's end
    fill      price an order sent at the start of bar j gets: its open (or the last close)
    vwap      session VWAP up to and including bar j
    daily     open, close, prev_close, session_len (bars in the session; 210 on half days)
    """

    close: pd.DataFrame
    fill: pd.DataFrame
    vwap: pd.DataFrame
    daily: pd.DataFrame


def make_bars(minute: pd.DataFrame, daily: pd.DataFrame) -> Bars:
    m = minute.copy()
    since_open = m["ts"] - m["date"].dt.tz_localize(m["ts"].dt.tz) - pd.Timedelta(hours=9.5)
    m["j"] = (since_open // pd.Timedelta(minutes=1)).astype(int)
    m = m[(m["j"] >= 0) & (m["j"] < SESSION)]

    def wide(col: str) -> pd.DataFrame:
        w = m.pivot_table(index="date", columns="j", values=col, aggfunc="last")
        return w.reindex(columns=range(SESSION))

    close, open_, vol = wide("close"), wide("open"), wide("volume")
    last = close.notna().to_numpy()[:, ::-1].argmax(axis=1)  # distance of last bar from the end
    # half days close at 13:00 (210 bars); a stray print in the 13:00 minute doesn't extend them
    session_len = pd.Series(np.where(SESSION - last <= 270, 210, SESSION), index=close.index)
    in_session = np.arange(SESSION)[None, :] < session_len.to_numpy()[:, None]
    close = close.ffill(axis=1).where(in_session)
    fill = open_.where(open_.notna(), close.shift(1, axis=1)).where(in_session)
    typical = (wide("high") + wide("low") + wide("close")) / 3
    pv = (typical * vol).fillna(0).cumsum(axis=1)
    cum_v = vol.fillna(0).cumsum(axis=1)
    vwap = (pv / cum_v.where(cum_v > 0)).where(in_session)

    d = daily.drop_duplicates("date", keep="last").set_index("date").sort_index()
    d = d[["open", "close"]].assign(prev_close=d["close"].shift(1))
    d = d.reindex(close.index).assign(session_len=session_len)
    return Bars(close=close, fill=fill, vwap=vwap, daily=d)


# ---------------------------------------------------------------- signals


def noise_sigma(close: pd.DataFrame, day_open: pd.Series, lookback: int = LOOKBACK) -> pd.DataFrame:
    """Average absolute move from the open at each minute over the previous `lookback` days.

    Row t uses days < t only. Up to two missing days in the window (half days) are tolerated.
    """
    move = (close.div(day_open, axis=0) - 1).abs()
    return move.rolling(lookback, min_periods=lookback - 2).mean().shift(1)


def noise_bands(bars: Bars, lookback: int = LOOKBACK) -> tuple[pd.DataFrame, pd.DataFrame]:
    sigma = noise_sigma(bars.close, bars.daily["open"], lookback)
    o, pc = bars.daily["open"], bars.daily["prev_close"]
    upper = sigma.add(1).mul(np.fmax(o, pc), axis=0)
    lower = sigma.rsub(1).mul(np.fmin(o, pc), axis=0)
    return upper, lower


def noise_targets(price, upper, lower, vwap) -> np.ndarray:
    """+1 above max(upper, VWAP), -1 below min(lower, VWAP), 0 otherwise (NaN -> 0)."""
    price, upper, lower, vwap = (np.asarray(x, float) for x in (price, upper, lower, vwap))
    with np.errstate(invalid="ignore"):
        long = price > np.fmax(upper, vwap)
        short = price < np.fmin(lower, vwap)
    ok = np.isfinite(upper) & np.isfinite(lower)
    return np.where(ok & long, 1, np.where(ok & short, -1, 0))


def _trade(day, side, entry_idx, entry_px, exit_idx, exit_px, reason, strategy) -> dict:
    return {
        "date": day,
        "strategy": strategy,
        "side": int(side),
        "entry_idx": int(entry_idx),
        "exit_idx": int(exit_idx),
        "entry_px": float(entry_px),
        "exit_px": float(exit_px),
        "exit_reason": reason,
    }


def day_trades(targets, checks, fill_row, close_px, session_len, day, strategy) -> list[dict]:
    """Turn one day's target positions (one per check) into round trips."""
    out, pos, entry = [], 0, None
    for target, j in zip(targets, checks, strict=True):
        if j + 1 >= session_len:
            break
        if target == pos:
            continue
        px = fill_row[j + 1]
        if not np.isfinite(px):
            continue
        if pos:
            out.append(_trade(day, pos, *entry, j + 1, px, "signal", strategy))
        entry, pos = (j + 1, px), int(target)
    if pos:
        out.append(_trade(day, pos, *entry, session_len, close_px, "close", strategy))
    return out


TRADE_COLS = ["date", "strategy", "side", "entry_idx", "exit_idx", "entry_px", "exit_px",
              "exit_reason"]  # fmt: skip


def noise_trades(bars: Bars, lookback: int = LOOKBACK) -> pd.DataFrame:
    upper, lower = noise_bands(bars, lookback)
    cols = list(CHECKS)
    rows = []
    for day in bars.close.index:
        d = bars.daily.loc[day]
        if not (np.isfinite(d["prev_close"]) and np.isfinite(d["close"])):
            continue
        targets = noise_targets(
            bars.close.loc[day, cols], upper.loc[day, cols], lower.loc[day, cols],
            bars.vwap.loc[day, cols],
        )  # fmt: skip
        fill = bars.fill.loc[day].to_numpy(float)
        n = int(d["session_len"])
        rows += day_trades(targets, CHECKS, fill, d["close"], n, day, "noise")
    return pd.DataFrame(rows, columns=TRADE_COLS)


def late_trades(bars: Bars, predictor: str = "rod", minutes: int = 30) -> pd.DataFrame:
    """One trade per day over the last `minutes`, side from the predictor (see module doc)."""
    rows = []
    for day in bars.close.index:
        d = bars.daily.loc[day]
        n = int(d["session_len"])
        if not (np.isfinite(d["prev_close"]) and np.isfinite(d["close"])) or n <= minutes + 30:
            continue
        signal_px = bars.close.loc[day, {"rod": n - minutes - 1, "onfh": 29}.get(predictor, 0)]
        side = 1 if predictor == "long" else int(np.sign(signal_px / d["prev_close"] - 1))
        px = bars.fill.loc[day, n - minutes]
        if side and np.isfinite(px) and np.isfinite(signal_px):
            rows.append(_trade(day, side, n - minutes, px, n, d["close"], "close", predictor))
    return pd.DataFrame(rows, columns=TRADE_COLS)


def daily_vol(daily: pd.DataFrame, lookback: int = LOOKBACK) -> pd.Series:
    """Std of close-to-close returns over the previous `lookback` days (known at the open)."""
    return daily["close"].pct_change().rolling(lookback).std().shift(1)


# ---------------------------------------------------------------- portfolio accounting

PLANS: dict[str, CostModel] = {
    "none": CostModel(per_share=0.0, min_per_order=0.0),
    "paper": CostModel(per_share=0.0035, min_per_order=0.0),
    **IBKR_PLANS,
}


@dataclass(frozen=True)
class Account:
    equity: float = 100_000.0
    plan: str = "paper"
    slippage: float = 0.001  # $/share on every fill except market-on-close exits
    vol_target: float | None = 0.02  # None = constant leverage
    leverage: float = 4.0  # the cap with a vol target, else the constant leverage


def run_portfolio(
    trades: pd.DataFrame, daily: pd.DataFrame, acct: Account, calendar: pd.DatetimeIndex
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily equity and per-trade fills. Size is set once per day from start-of-day equity."""
    vol = daily_vol(daily)
    by_day = dict(tuple(trades.groupby("date")))
    model = PLANS[acct.plan]
    equity, curve, fills = acct.equity, {}, []
    for d in calendar:
        t = by_day.get(d)
        if t is not None and equity > 0:
            lev = acct.leverage
            if acct.vol_target is not None:
                lev = min(acct.leverage, acct.vol_target / vol.get(d, np.nan))
            qty = np.floor(equity * lev / daily.loc[d, "open"]) if np.isfinite(lev) else 0.0
            if qty >= 1:
                side = t["side"].to_numpy()
                at_close = (t["exit_reason"] == "close").to_numpy()
                entry = t["entry_px"].to_numpy() + side * acct.slippage
                exit_ = t["exit_px"].to_numpy() - side * acct.slippage * ~at_close
                gross = side * qty * (exit_ - entry)
                costs = np.array(
                    [
                        model.total(s * qty, a) + model.total(-s * qty, b)
                        for s, a, b in zip(side, entry, exit_, strict=True)
                    ]
                )
                pnl = gross - costs
                equity += pnl.sum()
                fills.append(
                    t.assign(qty=qty, gross=gross, costs=costs, pnl=pnl, lev=lev).assign(
                        entry_fill=entry, exit_fill=exit_
                    )
                )
        curve[d] = equity
    curve = {calendar[0] - pd.Timedelta(days=1): acct.equity} | curve
    fills_df = pd.concat(fills, ignore_index=True) if fills else pd.DataFrame()
    return pd.Series(curve, name="equity"), fills_df


def bundle_trades(fills: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """run_portfolio fills -> the results-bundle trade format."""
    start = fills["date"].dt.tz_localize(massive.TZ) + pd.Timedelta(hours=9.5)
    minute = pd.Timedelta(minutes=1)
    return pd.DataFrame(
        {
            "entry_time": start + fills["entry_idx"] * minute,
            "exit_time": start + fills["exit_idx"] * minute,
            "symbol": ticker,
            "side": fills["side"],
            "qty": fills["qty"],
            "entry_px": fills["entry_fill"],
            "exit_px": fills["exit_fill"],
            "gross": fills["gross"],
            "costs": fills["costs"],
            "pnl": fills["pnl"],
            "exit_reason": fills["exit_reason"],
            "leverage": fills["lev"],
        }
    )


# ---------------------------------------------------------------- report


def periods(first: pd.Timestamp) -> dict[str, tuple[str | None, str | None]]:
    return {
        "all": (None, None),
        f"{first:%Y-%m}..2024-05 (pre-pub)": (None, "2024-05-14"),
        "2024-05+ (post-pub)": (PUBLISHED, None),
    }


def _between(index: pd.DatetimeIndex, a: str | None, b: str | None) -> pd.DatetimeIndex:
    keep = np.ones(len(index), bool)
    if a is not None:
        keep &= index >= pd.Timestamp(a)
    if b is not None:
        keep &= index <= pd.Timestamp(b)
    return index[keep]


def signal_quality(trades: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """Cost-free, unlevered quality: bps per trade and per day, hit rate, t-stat of daily P&L."""
    t = trades.assign(bps=trades["side"] * (trades["exit_px"] / trades["entry_px"] - 1) * 1e4)
    daily = t.groupby("date")["bps"].sum().reindex(calendar, fill_value=0.0)
    n = len(daily)
    return {
        "trades": len(t),
        "trades/day": len(t) / n,
        "bps/trade": t["bps"].mean(),
        "hit": (t["bps"] > 0).mean(),
        "bps/day": daily.mean(),
        "t (daily)": daily.mean() / daily.std() * np.sqrt(n) if daily.std() else np.nan,
        "ann. Sharpe 1x": daily.mean() / daily.std() * np.sqrt(252) if daily.std() else np.nan,
    }


def _portfolio_row(trades, daily, acct, calendar) -> dict:
    equity, fills = run_portfolio(trades, daily, acct, calendar)
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    n = len(fills)
    return summarize(equity) | {
        "trades/yr": n / years,
        "avg lev": float(fills.groupby("date")["lev"].first().mean()) if n else np.nan,
        "$/trade": float(fills["pnl"].mean()) if n else np.nan,
        "costs/trade": float(fills["costs"].mean()) if n else np.nan,
    }


def build(ticker: str = "SPY", rebuild: bool = False):
    minute, daily = load_bars(ticker, rebuild)
    bars = make_bars(minute, daily)
    sigma_ok = noise_sigma(bars.close, bars.daily["open"])[list(CHECKS)].notna().any(axis=1)
    vol_ok = daily_vol(bars.daily).notna()
    calendar = bars.close.index[(sigma_ok & vol_ok).to_numpy()]
    strategies = {
        "noise": noise_trades(bars),
        "late rod": late_trades(bars, "rod"),
        "late onfh": late_trades(bars, "onfh"),
        "late long (control)": late_trades(bars, "long"),
    }
    strategies = {k: v[v["date"].isin(calendar)] for k, v in strategies.items()}
    return bars, calendar, strategies


CAVEATS = [
    "Massive history starts Oct 2021, so the test covers ~4.5 years, ~2 of them post-publication.",
    "Fills at the next minute's open plus fixed per-share slippage; no queue or spread model.",
    "Unadjusted prices: ex-dividend days slightly distort the noise band and daily vol.",
]


def save(name, trades, bars, acct, calendar, ticker, strategy) -> str:
    from horizon_trader.backtest.bundle import save_run

    equity, fills = run_portfolio(trades, bars.daily, acct, calendar)
    bench = bars.daily["close"].reindex(equity.index[1:]).rename(ticker)
    meta = {
        "strategy": strategy,
        "params": {"account": acct.__dict__, "lookback": LOOKBACK, "checks": "HH:00/HH:30"},
        "oos_start": PUBLISHED,
        "chart": "massive_minute",
        "caveats": CAVEATS,
        "benchmark": f"{ticker} (price only)",
    }
    return save_run(name, equity, bundle_trades(fills, ticker), meta, bench).name


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--rebuild", action="store_true", help="re-read the minute files")
    p.add_argument("--save", action="store_true", help="save headline runs for the dashboard")
    args = p.parse_args()

    bars, calendar, strategies = build(args.ticker, args.rebuild)
    per = periods(calendar[0])
    span = f"{calendar[0]:%Y-%m-%d} .. {calendar[-1]:%Y-%m-%d}"
    print(f"\n{args.ticker} market intraday momentum, {span}")
    print(f"({len(calendar)} sessions; post-publication from {PUBLISHED})\n")

    rows = []
    for name, t in strategies.items():
        for label, (a, b) in per.items():
            cal = _between(calendar, a, b)
            rows.append(
                {"strategy": name, "period": label} | signal_quality(t[t["date"].isin(cal)], cal)
            )
    q = pd.DataFrame(rows).set_index(["strategy", "period"])
    print("Signal quality, before costs, unlevered (bps of notional):")
    with pd.option_context("display.width", 200):
        print(q.round(3).to_string())
    by_year = {
        name: t.assign(bps=t["side"] * (t["exit_px"] / t["entry_px"] - 1) * 1e4)
        .groupby(t["date"].dt.year)["bps"]
        .mean()
        for name, t in strategies.items()
    }
    print("\nbps/trade by year:")
    print(pd.DataFrame(by_year).round(2).to_string())

    paper = Account()
    mine = Account(equity=5_000.0, plan="fixed", slippage=0.005)
    setups = [
        ("paper: $100k, paper costs (0.35c + 0.1c slip)", paper),
        ("$100k no costs", replace(paper, plan="none", slippage=0.0)),
        ("$5k fixed 0c", replace(mine, slippage=0.0)),
        ("$5k fixed 0.5c", mine),
        ("$5k fixed 1c", replace(mine, slippage=0.01)),
        ("$5k tiered 0.5c", replace(mine, plan="tiered")),
        ("$5k fixed 0.5c, 1x (no vol target)", replace(mine, vol_target=None, leverage=1.0)),
    ]
    rows = []
    for name, t in strategies.items():
        for label, acct in setups:
            for plabel, (a, b) in per.items():
                cal = _between(calendar, a, b)
                row = _portfolio_row(t[t["date"].isin(cal)], bars.daily, acct, cal)
                rows.append({"strategy": name, "setup": label, "period": plabel} | row)
    for plabel, (a, b) in per.items():
        closes = bars.daily["close"].reindex(_between(calendar, a, b))
        rows.append({"strategy": f"{args.ticker} buy & hold", "setup": "price only",
                     "period": plabel} | summarize(closes))  # fmt: skip
    table = pd.DataFrame(rows).set_index(["strategy", "setup", "period"])
    cols = ["CAGR", "Sharpe", "max DD", "trades/yr", "avg lev", "$/trade", "costs/trade", "final"]
    fmt = {c: "{:.1%}".format for c in ("CAGR", "max DD")}
    fmt |= {"Sharpe": "{:.2f}".format, "trades/yr": "{:,.0f}".format, "avg lev": "{:.2f}".format}
    fmt |= {c: "{:,.2f}".format for c in ("$/trade", "costs/trade")} | {"final": "{:,.0f}".format}
    print("\nPortfolios (each period starts fresh; vol target 2%, max 4x unless noted):")
    with pd.option_context("display.width", 250, "display.max_rows", 300):
        print(table.reindex(columns=cols).to_string(formatters=fmt, na_rep="-"))

    if args.save:
        label = {
            "noise": "Noise-area intraday momentum (Zarattini, Aziz & Barbon 2024)",
            "late rod": "Last-half-hour momentum (Baltussen et al. 2021)",
        }
        for name, strategy in label.items():
            for setup, acct in (setups[0], setups[3]):
                run = f"{args.ticker} {name} {setup.split(':')[0].split(',')[0]}"
                print("saved", save(run, strategies[name], bars, acct, calendar, args.ticker,
                                    strategy))  # fmt: skip


if __name__ == "__main__":
    main()
