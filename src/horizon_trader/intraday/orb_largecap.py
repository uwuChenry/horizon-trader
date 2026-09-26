"""Large-cap filter for the Stocks-in-Play ORB: does trading only bigger stocks cut slippage?

    uv run python -m horizon_trader.intraday.orb_largecap [--save]

Pre-registered (before running): a dollar-volume floor as a point-in-time large-cap proxy,
14-day average volume x previous close >= $50M / $100M / $250M a day, applied BEFORE the
top-50 relative-volume cut (so large caps ranked low on the full list aren't lost). Everything
else is the baseline: top-1 by relative volume, 1 ATR stop, hold to the close.

Each threshold gets its OWN measured slippage (1-second bars on its own trades): the
hypothesis is that large caps are cheaper to trade, so a shared 4c assumption would hide the
very effect being tested. Two order types: stop-limit at the trigger (limit fills, measured
stop-outs) and stop-market (measured per-trade entry and stop-out slippage).

Pass rule: beats the unfiltered baseline's Sharpe in BOTH 2021-23 and 2024-26 ($5k, Tiered,
stop-limit), each half with fresh capital. 3 variants.
"""

from __future__ import annotations

import argparse
from dataclasses import replace

import pandas as pd

from horizon_trader.config import REPO_ROOT
from horizon_trader.intraday import orb
from horizon_trader.intraday import orb_grid as G
from horizon_trader.intraday import orb_ideas as I
from horizon_trader.intraday import slippage as S

THRESHOLDS = (0.0, 50e6, 100e6, 250e6)
CALS = {"train": ("2021-01-01", "2023-12-31"), "test": ("2024-01-01", "2100-01-01")}


def label(threshold: float) -> str:
    return (
        "no floor (baseline)" if threshold <= 0 else f"dollar volume >= ${threshold / 1e6:g}M/day"
    )


def _evaluate(trades: pd.DataFrame, cal: pd.DatetimeIndex, equity: float) -> dict:
    acct = orb.Account(equity=equity, top_n=1, plan="tiered", slippage=None)
    out = {}
    for name, (a, b) in {"all": ("1900", "2100"), **CALS}.items():
        c = cal[(cal >= pd.Timestamp(a)) & (cal <= pd.Timestamp(b))]
        t = trades[trades["date"].isin(c)]
        eq, fills = (
            orb.run_portfolio(t, acct, c)
            if len(t)
            else (pd.Series(equity, index=c), pd.DataFrame())
        )
        out |= G.metrics(eq, fills, name)
    return out


def run(threshold: float):
    rules = replace(I.RULES, min_dollar_volume=threshold)
    trades = orb.build_trades(rules)
    cal = pd.DatetimeIndex(sorted(trades["date"].unique()))
    base = I.select(trades, I.IDEAS[0], pd.Series(dtype=int))
    picked = base[base["triggered"].astype(bool)]
    measured = S.measure(picked, rules)  # per trade, from 1-second bars
    entry_mean = float(measured["entry_next_open"].mean())
    stop_mean = float(measured["exit_next_open"].mean())
    keys = sorted({(r.date, r.ticker) for r in picked.itertuples()})
    sim = I.simulate(base, I.IDEAS[0], I.Bars.load(trades, keys)).assign(exit_slip=stop_mean)
    market = measured.assign(
        entry_slip=measured["entry_next_open"].fillna(entry_mean),
        exit_slip=measured["exit_next_open"].fillna(stop_mean).fillna(0.0),
    )
    rows = []
    for order, t in (("stop-limit", sim), ("stop-market", market)):
        for equity in (5_000.0, 20_000.0):
            rows.append(
                {"filter": label(threshold), "order": order, "account": f"${equity / 1000:.0f}k"}
                | _evaluate(t, cal, equity)
            )
    stats = {
        "filter": label(threshold),
        "days with a trade": len(picked) / len(cal),
        "median price": float(picked["open"].median()),
        "entry slippage (c)": entry_mean * 100,
        "stop-out slippage (c)": stop_mean * 100,
        "entry slippage (bps)": float(
            (measured["entry_next_open"] / measured["entry_px"]).mean() * 1e4
        ),
    }
    return rows, stats, sim, cal


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save passing variants as bundles")
    args = p.parse_args()

    results, stats, sims = [], [], {}
    for th in THRESHOLDS:
        rows, st, sim, cal = run(th)
        results += rows
        stats.append(st)
        sims[th] = (sim, cal)
        print(f"  {label(th)}: done", flush=True)
    res = pd.DataFrame(results)
    res.to_parquet(REPO_ROOT / "data" / "results" / "orb_largecap.parquet")

    pd.set_option("display.width", 250)
    print("\n=== selection and measured slippage per filter (top-1 trades) ===")
    print(pd.DataFrame(stats).round(3).to_string(index=False))
    cols = [
        "all Sharpe",
        "all CAGR",
        "all max DD",
        "train Sharpe",
        "test Sharpe",
        "all trades",
        "all win rate",
    ]
    print("\n=== results (IBKR Tiered) ===")
    print(res.set_index(["filter", "order", "account"])[cols].round(3).to_string())

    sl = res[(res["order"] == "stop-limit") & (res["account"] == "$5k")].set_index("filter")
    base = sl.loc[label(0.0)]
    sl = sl.assign(
        passes=(sl["train Sharpe"] > base["train Sharpe"])
        & (sl["test Sharpe"] > base["test Sharpe"])
    )
    print("\n=== pass rule: beats the baseline in both halves (stop-limit, $5k) ===")
    print(sl[["train Sharpe", "test Sharpe", "passes"]].round(3).to_string())

    if args.save:
        for th in THRESHOLDS[1:]:
            if not bool(sl.loc[label(th), "passes"]):
                continue
            sim, cal = sims[th]
            acct = orb.Account(equity=5_000.0, top_n=1, plan="tiered", slippage=None)
            extra = {"caveats": [*orb.ORB_CAVEATS, "One of 3 pre-registered dollar-volume floors."]}
            rules = replace(I.RULES, min_dollar_volume=th)
            print(
                "saved",
                orb.save_orb_run(f"ORB large-cap: {label(th)}", sim, acct, rules, extra, cal),
            )


if __name__ == "__main__":
    main()
