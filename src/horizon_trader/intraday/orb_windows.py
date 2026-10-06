"""Is 5 minutes too short? ORB with 10, 15, 30 and 60-minute opening ranges.

    uv run python -m horizon_trader.intraday.orb_windows      (~3-5 min per new window, cached)

Pre-registered 2026-10-01, before running. The owner's hypothesis: a 5-minute range is mostly
noise and a longer one gives cleaner breakouts. The paper (Zarattini, Barbon & Aziz 2024) tested
5/15/30/60 and found 5 best (30-minute Sharpe 0.21), so the prior is against it.
  rules      everything as the 5-minute baseline except the window: relative volume of the
             first N minutes vs its 14-day mean, the paper's filters, direction of the N-minute
             candle, entry on a break of the range high/low after minute N, stop 1 ATR, exit
             at the close
  portfolio  $5k top-1, IBKR Tiered, 1c and 3c slippage per stop fill (minute bars; measured
             1-second fills exist only for the 5-minute version)
  pass       a window passes if its 1c Sharpe beats the 5-minute baseline in BOTH 2021-23 and
             2024+; with 4 windows tried, one marginal pass is expected by luck alone
"""

from __future__ import annotations

import argparse
from dataclasses import replace

import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.intraday import orb

WINDOWS = (5, 10, 15, 30, 60)
SLIPPAGE = (0.01, 0.03)


def evaluate(trades: pd.DataFrame, calendar: pd.DatetimeIndex, slippage: float) -> dict:
    acct = orb.Account(equity=5_000.0, top_n=1, plan="tiered", slippage=slippage)
    out = {}
    for label, (a, b) in orb.PERIODS.items():
        cal = calendar[
            (calendar >= pd.Timestamp(a or "1900")) & (calendar <= pd.Timestamp(b or "2100"))
        ]
        eq, fills = orb.run_portfolio(trades[trades["date"].isin(cal)], acct, cal)
        s = A.equity_stats(eq)
        out[f"Sharpe {label}"] = s["Sharpe"]
        if label == "all":
            out |= {
                "CAGR": s["CAGR"],
                "max DD": s["max DD"],
                "trades/yr": len(fills) / s["years"],
                "win rate": (fills["pnl"] > 0).mean() if len(fills) else float("nan"),
            }
    return out


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    rows, calendar = [], None
    for m in WINDOWS:
        trades = orb.build_trades(replace(orb.RULES, minutes=m, stop_atr=1.0))
        if calendar is None:  # every window uses the 5-minute run's trading days
            calendar = pd.DatetimeIndex(sorted(trades["date"].unique()))
        top1 = trades[(trades["rank"] == 1) & trades["triggered"]]
        r = orb.r_multiple(top1, "path")
        for slip in SLIPPAGE:
            row = {"window": f"{m} min", "slip": slip} | evaluate(trades, calendar, slip)
            rows.append(row | {"avg R (top-1, no costs)": r.mean()})
        print(f"  {m}-minute window done", flush=True)

    table = pd.DataFrame(rows).set_index(["window", "slip"])
    fmt = {c: "{:.2f}".format for c in table.columns if c.startswith("Sharpe") or "R" in c}
    fmt |= {c: "{:.1%}".format for c in ("CAGR", "max DD", "win rate")}
    fmt |= {"trades/yr": "{:.0f}".format}
    print(f"\nORB by opening-range window, {calendar[0].date()} .. {calendar[-1].date()}")
    print("$5k top-1, 1 ATR stop, IBKR Tiered\n")
    with pd.option_context("display.width", 250):
        print(table.apply(lambda col: col.map(fmt[col.name])).to_string())

    base = table.loc[("5 min", 0.01)]
    halves = [p for p in orb.PERIODS if p != "all"]
    print("\npre-registered verdict (1c Sharpe beats 5 min in both halves):")
    for m in WINDOWS[1:]:
        r = table.loc[(f"{m} min", 0.01)]
        ok = all(r[f"Sharpe {p}"] > base[f"Sharpe {p}"] for p in halves)
        print(f"  {m:>2} min: {'PASS' if ok else 'fail'}")


if __name__ == "__main__":
    main()
