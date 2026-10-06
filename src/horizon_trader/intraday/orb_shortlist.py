"""Can ORB's daily pick be found live without a full-market real-time feed?

    uv run python -m horizon_trader.intraday.orb_shortlist

The backtest ranks every US common stock by first-5-minute relative volume. Live, IBKR streams
about 100 symbols at once and Massive's real-time plan isn't worth its price, so the pick has
to come from a shortlist known in time. Inside a shortlist the exact ORB rule runs unchanged
(14-day relative volume, the paper's filters, top 1): live data for <= 100 names is affordable.

Pre-registered 2026-10-01, before running:
  scanner50     (option 3) IBKR's "5min Volume vs Average Volume" scanner at 9:35
                (SCAN_stVolumeVsAvg5min_DESC, max 50 rows), approximated as the top 50 by
                opening-range volume / 14-day average DAILY volume, among stocks opening above
                $5 with average volume >= 1M (filters the scanner itself can apply). IBKR's
                exact average and its ETF handling are unknown: scanner_log checks them live.
  premarket100  (option 1) the top 100 by pre-market volume from 4:00 to 9:10 (what a
                15-minute-delayed feed shows at 9:25) / 14-day average daily volume, among
                stocks with previous close > $5, average volume >= 1M and ATR > $0.50.
  gap100        (option 1, simpler data) the top 100 by |last pre-market price by 9:10 /
                previous close - 1|, same filters.
Measured: coverage = share of days whose backtest top-1 is in the shortlist, and the $5k
top-1 strategy (1 ATR stop, IBKR Tiered, 1c and 3c slippage) restricted to the shortlist vs
the full-market baseline, overall and in both halves.
Verdict per shortlist, fixed in advance: USABLE if coverage >= 90%; USABLE WITH HAIRCUT if
75-90% and the 1c Sharpe stays within 0.15 of the baseline in both halves; NOT USABLE otherwise.
Other list sizes (25/50/100/200) are printed for information only.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.datasources import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

RULES = replace(orb.RULES, stop_atr=1.0)
PM_START = pd.Timedelta(hours=-5, minutes=-30)  # 4:00 = 9:30 - 5h30
PM_CUTOFF = pd.Timedelta(minutes=-20)  # 9:10
SIZES = (25, 50, 100, 200)
PRIMARY = {"scanner50": 50, "premarket100": 100, "gap100": 100}
SLIPPAGE = (0.01, 0.03)


def _pm_job(d: date) -> pd.DataFrame:
    start = F.session_open(d)
    window = [("ts", ">=", start + PM_START), ("ts", "<", start + PM_CUTOFF)]
    bars = pd.read_parquet(massive.local_path("minute", d), filters=window)
    g = bars.sort_values("ts").groupby("ticker", sort=True)
    out = pd.DataFrame({"pm_volume": g["volume"].sum(), "pm_last": g["close"].last()})
    return out.reset_index().assign(date=pd.Timestamp(d))


def premarket(days: list[date], n_workers=None) -> pd.DataFrame:
    """Pre-market volume and last price (4:00-9:10) per day and ticker, cached (long format)."""
    name = "premarket_0910"
    cached = orb._derived(name)
    have = set() if cached is None else set(cached["date"].dt.date)
    new = orb._parallel(_pm_job, [d for d in days if d not in have], n_workers, "pre-market")
    if new:
        cached = pd.concat([cached, *new] if cached is not None else new, ignore_index=True)
        orb._save(cached, name)
    return cached[cached["date"].dt.date.isin(set(days))]


def shortlist_scores(panels: dict, pm: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Date x ticker score per shortlist, NaN where the stock isn't eligible."""
    avg_vol = panels["avg_volume"]
    pm_vol = pm.pivot(index="date", columns="ticker", values="pm_volume").reindex_like(avg_vol)
    pm_last = pm.pivot(index="date", columns="ticker", values="pm_last").reindex_like(avg_vol)
    liquid = avg_vol >= RULES.min_avg_volume
    pre_open = liquid & (panels["prev_close"] > RULES.min_price) & (panels["atr"] > RULES.min_atr)
    at_935 = liquid & (panels["open"] > RULES.min_price)
    return {
        "scanner": (panels["or_volume"] / avg_vol).where(at_935),
        "premarket": (pm_vol.fillna(0) / avg_vol).where(pre_open),
        "gap": (pm_last / panels["prev_close"] - 1).abs().where(pre_open),
    }


def in_list(score: pd.DataFrame, n: int) -> pd.DataFrame:
    return score.rank(axis=1, ascending=False, method="first") <= n


def restrict(trades: pd.DataFrame, member: pd.DataFrame) -> pd.DataFrame:
    """Keep each day's candidates that are on the shortlist, re-ranked in the same order."""
    stacked = member.stack()
    keys = pd.MultiIndex.from_arrays([trades["date"], trades["ticker"]])
    keep = stacked.reindex(keys).fillna(False).to_numpy(bool)
    t = trades[keep].sort_values(["date", "rank"], kind="stable")
    return t.assign(rank=t.groupby("date").cumcount() + 1)


def coverage(top1: pd.DataFrame, member: pd.DataFrame) -> float:
    stacked = member.stack()
    keys = pd.MultiIndex.from_arrays([top1["date"], top1["ticker"]])
    return float(stacked.reindex(keys).fillna(False).mean())


def strategy(trades: pd.DataFrame, calendar: pd.DatetimeIndex, slippage: float) -> dict:
    acct = orb.Account(equity=5_000.0, top_n=1, plan="tiered", slippage=slippage)
    out = {}
    for label, (a, b) in orb.PERIODS.items():
        cal = calendar[
            (calendar >= pd.Timestamp(a or "1900")) & (calendar <= pd.Timestamp(b or "2100"))
        ]
        eq, _ = orb.run_portfolio(trades[trades["date"].isin(cal)], acct, cal)
        s = A.equity_stats(eq)
        out[f"Sharpe {label}"] = s["Sharpe"]
        if label == "all":
            out |= {"CAGR": s["CAGR"], "max DD": s["max DD"]}
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    trades = orb.build_trades(RULES)
    days = sorted(trades["date"].dt.date.unique())
    calendar = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    print(f"ORB shortlist check, {days[0]} .. {days[-1]} ({len(days)} days)", flush=True)

    panels = orb.feature_panels(RULES, days, massive.local_days("day"))
    panels = {k: v.reindex(calendar) for k, v in panels.items()}
    scores = shortlist_scores(panels, premarket(days))
    top1 = trades[trades["rank"] == 1]

    # sanity: the refactored feature path reproduces the cached top-1 on sample days
    rng = np.random.default_rng(0)
    for t in rng.choice(top1["date"].unique(), 10, replace=False):
        best = orb.select_candidates(orb.day_frame(panels, pd.Timestamp(t)), RULES).index[0]
        assert best == top1.loc[top1["date"] == t, "ticker"].iloc[0], t

    rows = []
    for name, score in scores.items():
        for n in SIZES:
            c = coverage(top1, in_list(score, n))
            rows.append({"shortlist": name, "size": n, "coverage": c})
    cov = pd.DataFrame(rows).pivot(index="shortlist", columns="size", values="coverage")
    print("\ncoverage: share of days whose full-market top-1 is on the shortlist")
    print(cov.map("{:.0%}".format).to_string())

    results = []
    for slip in SLIPPAGE:
        base = strategy(trades, calendar, slip)
        results.append({"setup": "baseline (full market)", "slip": slip} | base)
        for key, n in PRIMARY.items():
            member = in_list(scores[key.rstrip("0123456789")], n)
            row = strategy(restrict(trades, member), calendar, slip)
            results.append({"setup": key, "slip": slip} | row)
    res = pd.DataFrame(results).set_index(["setup", "slip"])
    print("\n$5k top-1, 1 ATR stop, IBKR Tiered, restricted to each shortlist")
    fmt = {c: "{:.2f}".format for c in res.columns if c.startswith("Sharpe")}
    fmt |= {"CAGR": "{:.1%}".format, "max DD": "{:.1%}".format}
    print(res.apply(lambda col: col.map(fmt[col.name])).to_string())

    print("\nverdicts (pre-registered):")
    base = res.loc[("baseline (full market)", 0.01)]
    for key, n in PRIMARY.items():
        c = cov.loc[key.rstrip("0123456789"), n]
        r = res.loc[(key, 0.01)]
        halves = [p for p in orb.PERIODS if p != "all"]
        close = all(base[f"Sharpe {p}"] - r[f"Sharpe {p}"] <= 0.15 for p in halves)
        verdict = (
            "USABLE" if c >= 0.90
            else "USABLE WITH HAIRCUT" if c >= 0.75 and close
            else "NOT USABLE"
        )  # fmt: skip
        print(f"  {key:13s} coverage {c:.0%}  -> {verdict}")


if __name__ == "__main__":
    main()
