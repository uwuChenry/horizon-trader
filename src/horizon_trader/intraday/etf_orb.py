"""Opening Range Breakout on liquid ETFs, where slippage should be small.

    uv run python -m horizon_trader.intraday.etf_orb [--tickers QQQ,SPY,...] [--save]

Tickers: QQQ, SPY (1x indexes), TQQQ, SPXL, UPRO (3x Nasdaq-100 / S&P 500), SOXL (3x
semiconductors) and SMH (1x semiconductors, SOXL's control). SPXL and UPRO trade ~1M
shares/day (TQQQ/SOXL 58-65M), so their measured slippage decides whether they're usable.

Rule sets (pre-registered; A and C are Zarattini & Aziz 2023, "Can Day Trading Really Be
Profitable?", SSRN 4416622, first posted 2023-04-24; confirmed against the PDF):
  A  paper 2023      direction of the first 5-minute candle; market entry at the 9:35 open;
                     stop at the first candle's low (long) / high (short); target 10R, else
                     exit at the close. The paper's main rules (Table 1).
  B  stock baseline  our Stocks-in-Play baseline: stop-limit entry at the first candle's
                     high / low, stop 1 ATR from the fill, hold to the close.
  C  paper optimum   market entry at 9:35, stop 5% of the 14-day ATR, hold to the close: the
                     after-the-fact best of the paper's section 4 (reported +9,350% on TQQQ,
                     which the authors themselves call unrealistic without slippage).
Sizing as the paper: shares = min(1% of equity / R, 4 x equity / price). On a 3x ETF the 4x
cap means up to 12x the underlying index.

Slippage (entries and stop-outs are marketable; targets are limits; the close is MOC):
  0c        none (the paper's assumption)
  1c        1c per share on market entries and stop-outs
  measured  per ticker and rule, from 1-second bars on a sample of trades: the first trade
            one second after the order (the same estimator as for the stock ORB)
Costs: IBKR Pro Tiered, $5k and $20k. Plus one paper-replication row: rule A, $25k, the
paper's $0.0005/share commission, 0c.

Protocol (fixed before running): train 2021-10 .. 2023-12, test 2024-01 .. 2026-09, and
before / after publication (2023-04-24). A (ticker, rule) is a PAPER-TRADE CANDIDATE only if,
with measured slippage at $5k Tiered, its Sharpe is >= 0.5 in BOTH train and test, and
positive after publication. 21 combinations are tested; the best one's deflated Sharpe is
reported for 21 trials.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.config import REPO_ROOT
from horizon_trader.data import massive, massive_ref
from horizon_trader.intraday import features as F
from horizon_trader.intraday import market_momentum as MM
from horizon_trader.intraday import orb
from horizon_trader.intraday import orb_grid as G
from horizon_trader.intraday import orb_ideas as I
from horizon_trader.intraday.slippage import fetch_seconds, fill_slippage

TICKERS = ("QQQ", "SPY", "TQQQ", "SPXL", "UPRO", "SOXL", "SMH")
PUBLISHED = pd.Timestamp("2023-04-24")
TRAIN, TEST = ("2021-01-01", "2023-12-31"), ("2024-01-01", "2100-01-01")
OR_MINUTES = 5
SAMPLE = 300  # trades per (ticker, rule) whose fills are measured on 1-second bars
PASS_SHARPE = 0.5


@dataclass(frozen=True)
class EtfRule:
    key: str
    name: str
    entry: str  # "open" = market at the 9:35 open, "stop_limit" = limit at the range's edge
    stop: str  # "range" = the first candle's opposite extreme, "atr" = stop_atr x ATR
    stop_atr: float = 0.0
    target: float | None = None  # in R; None = hold to the close


RULES = [
    EtfRule("A", "A paper 2023 (range stop, 10R target)", "open", "range", target=10.0),
    EtfRule("B", "B stock baseline (stop-limit, 1 ATR, hold)", "stop_limit", "atr", 1.0),
    EtfRule("C", "C paper optimum (5% ATR stop, hold)", "open", "atr", 0.05),
]


# ---------------------------------------------------------------- data


def ticker_days(ticker: str) -> tuple[pd.DataFrame, I.Bars]:
    """Per day: opening range, direction, split-safe ATR, official close; plus the bars after
    the opening range as an orb_ideas.Bars mapping (what the exit simulators index)."""
    minute, daily = MM.load_bars(ticker)
    daily = daily.drop_duplicates("date", keep="last").sort_values("date")
    panels = {f: daily.set_index("date")[[f]].rename(columns={f: ticker}) for f in F.DAILY_FIELDS}
    factor = F.split_factors(
        panels["open"].index, panels["open"].columns, massive_ref.load_splits()
    )
    feats = F.daily_features(panels, factor)
    rows, data = [], {}
    for day, g in minute.sort_values("ts").groupby("date"):
        start = F.session_open(day.date())
        cut = start + pd.Timedelta(minutes=OR_MINUTES)
        opening, post = g[g["ts"] < cut], g[g["ts"] >= cut]
        if opening.empty or opening["ts"].iloc[0] != start or post.empty:
            continue
        side = int(np.sign(opening["close"].iloc[-1] - opening["open"].iloc[0]))
        rows.append(
            {
                "date": day,
                "side": side,
                "or_high": opening["high"].max(),
                "or_low": opening["low"].min(),
                "atr": feats["atr"][ticker].get(day, np.nan),
                "close": feats["close"][ticker].get(day, np.nan),
            }
        )
        data[(day, ticker)] = (
            post["ts"].to_numpy(),
            *(post[f].to_numpy(float) for f in ("open", "high", "low")),
        )
    days = pd.DataFrame(rows)
    return days[(days["side"] != 0) & days["atr"].notna() & days["close"].notna()], I.Bars(data)


# ---------------------------------------------------------------- simulation


def simulate_open_entry(
    days: pd.DataFrame, bars: I.Bars, ticker: str, rule: EtfRule
) -> pd.DataFrame:
    """Rules A and C: market entry at the first post-range bar's open. The whole bar comes after
    the fill, so the minute bars resolve its stop exactly (only a target reached inside the
    fill minute is missed, which for a 10R target is negligible)."""
    rows = []
    for r in days.itertuples():
        ts, o, h, lo = bars.get(r.date, ticker)
        side, fill = r.side, o[0]
        if rule.stop == "range":
            dist = fill - r.or_low if side > 0 else r.or_high - fill
        else:
            dist = rule.stop_atr * r.atr
        if not dist > 0:  # opened beyond the range's far side: no valid stop
            continue
        target_rule = ("target", rule.target) if rule.target else ("hold", 0.0)
        px, stopped, x = I.manage_exit(o, h, lo, 0, fill, side, dist, r.close, *target_rule)
        rows.append(_row(r.date, ticker, side, fill, dist, ts, 0, px, stopped, x, len(o)))
    return pd.DataFrame(rows)


def _row(day, ticker, side, fill, dist, ts, j, px, stopped, x, n) -> dict:
    t = pd.Timestamp(ts[j])
    reason = "stop" if stopped else ("close" if x >= n else "target")
    return {
        "date": day,
        "ticker": ticker,
        "rank": 1,
        "triggered": True,
        "side": side,
        "entry_px": fill,
        "stop_dist": dist,
        "entry_idx": j,
        "entry_time": t if t.tzinfo else t.tz_localize("UTC").tz_convert(massive.TZ),
        "exit_px_path": px,
        "stopped_path": stopped,
        "exit_idx_path": x,
        "exit_minute": pd.Timestamp(ts[min(x, n - 1)]),
        "exit_reason": reason,
    }


def simulate_stop_limit(
    days: pd.DataFrame, bars: I.Bars, ticker: str, rule: EtfRule
) -> pd.DataFrame:
    """Rule B through the stock ORB's own simulator (orb_grid.simulate_config): stop-limit at
    the range's edge, filled from 1-second bars, stop checked on the seconds after the fill."""
    picked = []
    for r in days.itertuples():
        ts, o, h, lo = bars.get(r.date, ticker)
        level = r.or_high if r.side > 0 else r.or_low
        hits = np.flatnonzero(h >= level) if r.side > 0 else np.flatnonzero(lo <= level)
        if not len(hits):
            continue
        k = int(hits[0])
        t = pd.Timestamp(ts[k])
        picked.append(
            {
                "date": r.date,
                "ticker": ticker,
                "side": r.side,
                "entry_idx": k,
                "level": level,
                "atr": r.atr,
                "close": r.close,
                "relvol": np.nan,
                "entry_time": t if t.tzinfo else t.tz_localize("UTC").tz_convert(massive.TZ),
                "entry_px": max(level, o[k]) if r.side > 0 else min(level, o[k]),
            }
        )
    picked = pd.DataFrame(picked)
    secs = _fetch({(p.ticker, p.entry_time) for p in picked.itertuples()})
    sim = G.simulate_config(picked, rule.stop_atr, rule.target, "limit", bars, secs)
    n_bars = {k: len(v[0]) for k, v in bars._data.items()}
    exit_min = [
        bars.get(s.date, ticker)[0][min(s.exit_idx_path, n_bars[(s.date, ticker)] - 1)]
        for s in sim.itertuples()
    ]
    return sim.assign(
        exit_minute=pd.to_datetime(exit_min).tz_convert(massive.TZ) if len(sim) else []
    )


def _fetch(keys, threads: int = 6) -> dict:
    keys = sorted(keys)
    with ThreadPoolExecutor(max_workers=threads) as pool:
        return dict(zip(keys, pool.map(lambda k: fetch_seconds(*k), keys), strict=True))


# ---------------------------------------------------------------- measured slippage


HALF_SPREAD = 0.005  # $/share: half of the 1c spread these ETFs usually trade at


def measure(trades: pd.DataFrame, rule: EtfRule, seed: int = 0) -> dict:
    """Mean slippage ($/share) on a random sample of entries and stop-outs, from 1-second bars.

    Stop-outs are triggered by price moving against us, so their slippage (the first trade one
    second after the trigger vs the stop) is floored at zero, as for the stock ORB. Market
    entries at 9:35 are sent at a fixed time, not triggered by price: the move in the next
    second is as likely to help as to hurt, so its SIGNED mean is used (flooring it would turn
    random noise into fake slippage), plus half the spread paid by any market order.
    """
    out = {"entry": 0.0, "entry_drift": np.nan, "stop_out": np.nan, "n_entry": 0, "n_stop": 0}
    if rule.entry == "open":
        s = trades.sample(min(SAMPLE, len(trades)), random_state=seed)
        secs = _fetch({(r.ticker, r.entry_time) for r in s.itertuples()})
        drift = []
        for r in s.itertuples():
            b = secs[(r.ticker, r.entry_time)]
            if len(b) >= 2:  # first trade of the minute = modeled fill; one second later = real
                drift.append(r.side * (b["open"].iloc[1] - r.entry_px))
        mean_drift = float(np.mean(drift)) if drift else 0.0
        out |= {
            "entry": max(mean_drift, 0.0) + HALF_SPREAD,
            "entry_drift": mean_drift,
            "n_entry": len(drift),
        }
    stops = trades[trades["stopped_path"].astype(bool)]
    s = stops.sample(min(SAMPLE, len(stops)), random_state=seed)
    secs = _fetch({(r.ticker, r.exit_minute) for r in s.itertuples()})
    slips = []
    for r in s.itertuples():
        stop_px = r.entry_px - r.side * r.stop_dist
        v = fill_slippage(secs[(r.ticker, r.exit_minute)], -r.side, stop_px, r.exit_px_path)[
            "next_open"
        ]
        if pd.notna(v):
            slips.append(v)
    out |= {"stop_out": float(np.mean(slips)) if slips else np.nan, "n_stop": len(slips)}
    return out


# ---------------------------------------------------------------- evaluation


def periods(cal: pd.DatetimeIndex) -> dict[str, pd.DatetimeIndex]:
    return {
        "all": cal,
        "train": cal[(cal >= TRAIN[0]) & (cal <= TRAIN[1])],
        "test": cal[(cal >= TEST[0]) & (cal <= TEST[1])],
        "pre-pub": cal[cal < PUBLISHED],
        "post-pub": cal[cal >= PUBLISHED],
    }


def evaluate(trades, cal, equity, plan, slip_in, slip_out) -> dict:
    acct = orb.Account(equity=equity, top_n=1, plan=plan, slippage=None)
    t = trades.assign(entry_slip=slip_in, exit_slip=slip_out)
    row = {}
    for name, c in periods(cal).items():
        tt = t[t["date"].isin(c)]
        eq, fills = (
            orb.run_portfolio(tt, acct, c)
            if len(tt)
            else (pd.Series(equity, index=c), pd.DataFrame())
        )
        row |= G.metrics(eq, fills, name)
        if name == "all":
            row["_equity"] = eq
    return row


def run_ticker(ticker: str) -> tuple[list[dict], dict, dict]:
    days, bars = ticker_days(ticker)
    cal = pd.DatetimeIndex(sorted(days["date"]))
    rows, sims, slips = [], {}, {}
    for rule in RULES:
        sim = (
            simulate_open_entry(days, bars, ticker, rule)
            if rule.entry == "open"
            else simulate_stop_limit(days, bars, ticker, rule)
        )
        sims[rule.key] = sim
        m = measure(sim, rule)
        slips[rule.key] = m
        measured_in = 0.0 if rule.entry == "stop_limit" else m["entry"]
        measured_out = m["stop_out"] if pd.notna(m["stop_out"]) else 0.01
        scenarios = {
            "0c": (0.0, 0.0),
            "1c": (0.0 if rule.entry == "stop_limit" else 0.01, 0.01),
            "measured": (measured_in, measured_out),
        }
        for scen, (s_in, s_out) in scenarios.items():
            for equity in (5_000.0, 20_000.0):
                r = evaluate(sim, cal, equity, "tiered", s_in, s_out)
                rows.append(
                    {
                        "ticker": ticker,
                        "rule": rule.name,
                        "scenario": scen,
                        "account": f"${equity / 1000:.0f}k",
                    }
                    | r
                )
        if rule.key == "A":
            r = evaluate(sim, cal, 25_000.0, "paper_2023", 0.0, 0.0)
            rows.append(
                {
                    "ticker": ticker,
                    "rule": rule.name,
                    "scenario": "paper replication",
                    "account": "$25k",
                }
                | r
            )
    return rows, sims, slips


def buy_and_hold(ticker: str) -> dict:
    _, daily = MM.load_bars(ticker)
    d = daily.drop_duplicates("date").set_index("date")["close"]
    panels = {"close": d.to_frame(ticker)}
    factor = F.split_factors(d.index, pd.Index([ticker]), massive_ref.load_splits())
    px = (panels["close"] * factor)[ticker]  # split-adjusted, price only
    s = A.equity_stats(px)
    return {
        "ticker": ticker,
        "CAGR": s["CAGR"],
        "Sharpe": s["Sharpe"],
        "max DD": s["max DD"],
        "_returns": px.pct_change(),
    }


# ---------------------------------------------------------------- report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--tickers", default=",".join(TICKERS))
    p.add_argument("--save", action="store_true", help="save rule-A runs and any candidates")
    args = p.parse_args()
    tickers = args.tickers.split(",")

    t0 = perf_counter()
    with ProcessPoolExecutor(max_workers=min(len(tickers), orb.workers())) as pool:
        out = dict(zip(tickers, pool.map(run_ticker, tickers), strict=True))
    rows = [r for t in tickers for r in out[t][0]]
    res = pd.DataFrame(rows)
    bh = {t: buy_and_hold(t) for t in tickers}
    spy = bh.get("SPY", buy_and_hold("SPY"))["_returns"]
    res["corr SPY"] = [
        r["_equity"].pct_change().corr(spy.reindex(r["_equity"].index)) for r in rows
    ]
    path = REPO_ROOT / "data" / "results" / "etf_orb.parquet"
    res.drop(columns="_equity").to_parquet(path)
    print(f"{len(res)} runs over {len(tickers)} tickers in {perf_counter() - t0:.0f}s -> {path}\n")

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print("=== measured slippage (cents/share; sample of up to 300 trades per ticker and rule) ===")
    sl = pd.DataFrame(
        [
            {
                "ticker": t,
                "rule": k,
                "entry (market at 9:35)": v["entry"] * 100,
                "entry 1s drift (signed)": v["entry_drift"] * 100,
                "stop-outs": v["stop_out"] * 100,
                "entries measured": v["n_entry"],
                "stop-outs measured": v["n_stop"],
            }
            for t in tickers
            for k, v in out[t][2].items()
        ]
    )
    print(sl.round(2).to_string(index=False))

    main_cols = [
        "all Sharpe",
        "all CAGR",
        "all max DD",
        "train Sharpe",
        "test Sharpe",
        "post-pub Sharpe",
        "all win rate",
        "all trades",
        "corr SPY",
    ]
    m = res[(res["scenario"] == "measured") & (res["account"] == "$5k")].copy()
    m["candidate"] = (
        (m["train Sharpe"] >= PASS_SHARPE)
        & (m["test Sharpe"] >= PASS_SHARPE)
        & (m["post-pub Sharpe"] > 0)
    )
    print(
        "\n=== measured slippage, $5k, IBKR Tiered ===\n"
        "(candidate = Sharpe >= 0.5 in train AND test, > 0 after publication)"
    )
    print(m.set_index(["ticker", "rule"])[[*main_cols, "candidate"]].round(3).to_string())

    print("\n=== full-period Sharpe by slippage scenario and account ===")
    pv = res[res["scenario"] != "paper replication"].pivot_table(
        index=["ticker", "rule"], columns=["scenario", "account"], values="all Sharpe"
    )
    print(pv.round(2).to_string())

    print(
        "\n=== paper replication: rule A, $25k, $0.0005/share, 0c ===\n"
        "(paper, 2016 - Feb 2023: QQQ Sharpe 1.12, TQQQ 1.19)"
    )
    rep = res[res["scenario"] == "paper replication"].set_index("ticker")
    print(
        rep[
            [
                "all Sharpe",
                "all CAGR",
                "all max DD",
                "pre-pub Sharpe",
                "post-pub Sharpe",
                "all win rate",
                "all avg R",
            ]
        ]
        .round(3)
        .to_string()
    )

    print("\n=== buy & hold (price only, split-adjusted) ===")
    print(
        pd.DataFrame([{k: v for k, v in b.items() if k != "_returns"} for b in bh.values()])
        .round(3)
        .to_string(index=False)
    )

    trial_var = m["all daily SR"].var()
    best = m.loc[m["all Sharpe"].idxmax()]
    eq = [
        r
        for r in rows
        if r["ticker"] == best.ticker
        and r["rule"] == best.rule
        and r["scenario"] == "measured"
        and r["account"] == "$5k"
    ][0]["_equity"]
    dsr = A.deflated_sharpe(eq.pct_change().dropna(), len(m), trial_var)
    print(
        f"\n=== deflated Sharpe, best measured $5k combination ===\n"
        f"({best.ticker}, {best.rule}; {len(m)} trials)"
    )
    print({k: round(v, 3) for k, v in dsr.items()})

    if args.save:
        cands = set(
            zip(m.loc[m["candidate"], "ticker"], m.loc[m["candidate"], "rule"], strict=True)
        )
        for t in tickers:
            for rule in RULES:
                if rule.key != "A" and (t, rule.name) not in cands:
                    continue
                sim = out[t][1][rule.key]
                sl_ = out[t][2][rule.key]
                s_in = 0.0 if rule.entry == "stop_limit" else sl_["entry"]
                s_out = sl_["stop_out"] if pd.notna(sl_["stop_out"]) else 0.01
                acct = orb.Account(equity=5_000.0, top_n=1, plan="tiered", slippage=None)
                cal = pd.DatetimeIndex(sorted(sim["date"].unique()))
                extra = {
                    "strategy": "ETF ORB (Zarattini & Aziz 2023)",
                    "caveats": [
                        "Slippage measured on a sample of 1-second bars (trades, not quotes).",
                        f"One of {len(m)} ticker x rule combinations tested (etf_orb.py).",
                    ],
                }
                print(
                    "saved",
                    orb.save_orb_run(
                        f"ETF ORB {t} {rule.name}, $5k measured",
                        sim.assign(entry_slip=s_in, exit_slip=s_out),
                        acct,
                        I.RULES,
                        extra,
                        cal,
                    ),
                )


if __name__ == "__main__":
    main()
