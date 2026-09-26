"""Catching the next Nvidia: momentum among the largest companies, with point-in-time data.

    uv run python -m horizon_trader.backtest.winners [--save]

--save writes dashboard bundles with daily holdings and each month's ranking (Holdings page).

Pre-registered (2026-09-26, before running):
  universe   each month-end, the 200 largest US companies by market cap AS OF THAT DATE
             (Massive point-in-time caps; delisted companies included; one share class each)
  signal     12-1 momentum: the return from 12 months ago to 1 month ago (Jegadeesh & Titman),
             and the shorter 6-1 variant
  portfolio  the top 10 and top 20 by momentum, equal weight, rebalanced monthly: formed at
             the month-end close, traded at the next open
  benchmark  the same 200 companies, equal weight (the project's rule for stock-selection
             alphas), plus SPY and QQQ
  costs      the daily book's simulator ($5k, IBKR Pro Tiered, 5 bps slippage, 2% rebalance
             band, fractional shares), and gross (no costs) for comparison
Also reported: which of the period's biggest winners the strategy held and how much of each
run it missed before buying; its worst picks; and a survivorship contrast (the same rule on
TODAY's 200 largest companies, the kind of backtest that looks great and isn't real).
Everything is price only (no dividends). 4 variants (2 signals x 2 portfolio sizes).
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.backtest import megacap as M
from horizon_trader.backtest.sim import simulate
from horizon_trader.config import ExecutionSettings
from horizon_trader.execution.costs import ibkr_costs

UNIVERSE = 200
SIGNALS = {"12-1": (252, 21), "6-1": (126, 21)}  # (lookback, skip) in trading days
SIZES = (10, 20)
CAPITAL = 5_000.0
N_WINNERS = 15
MAX_MISSING = 10  # trading days without a price allowed inside a momentum window (halts)


def momentum(
    adj: pd.DataFrame, lookback: int, skip: int, max_missing: int = MAX_MISSING
) -> pd.DataFrame:
    """Return from `lookback` to `skip` trading days ago; row t uses prices up to t only.
    Unknown (NaN) when the window has more than `max_missing` days without a price: a long
    gap usually means the ticker was delisted and later reused (BNY was a ~$10 muni fund
    until Bank of New York Mellon took the symbol in 2026; SPCX was a SPAC ETF before
    SpaceX), and the "return" across it compares two different securities."""
    mom = adj.shift(skip) / adj.shift(lookback) - 1
    missing = adj.isna().rolling(lookback - skip + 1).sum().shift(skip)
    return mom.where(missing <= max_missing)


def current_listing(px: pd.Series, max_gap_days: int = 30) -> pd.Series:
    """The part of a price series after its last gap of more than `max_gap_days` calendar
    days, i.e. the security trading under the ticker now. For after-the-fact reports only."""
    s = px.dropna()
    gaps = s.index.to_series().diff().dt.days
    big = gaps[gaps > max_gap_days]
    return s[s.index >= big.index[-1]] if len(big) else s


def schedules(data: dict, lookback: int, skip: int, n: int, universe_at=None) -> dict:
    """{formation date: equal weights} for the top n by momentum within the universe.
    `universe_at(date)` returns that date's universe (default: the point-in-time top 200)."""
    mom = momentum(data["adj"], lookback, skip)
    out = {}
    for d in data["ends"]:
        uni = universe_at(d) if universe_at else point_in_time_universe(data, d)
        m = mom.loc[d].reindex(uni).dropna()
        if len(m) < n * 2:  # not enough history yet (the first year)
            continue
        out[d] = pd.Series(1.0, index=m.nlargest(n).index)
    return out


def point_in_time_universe(data: dict, d: pd.Timestamp) -> list[str]:
    return list(M.top_n(data["caps"][data["caps"]["date"] == d], UNIVERSE).index)


def universe_schedule(data: dict, dates: list[pd.Timestamp], universe_at=None) -> dict:
    return {
        d: pd.Series(1.0, index=(universe_at or (lambda x: point_in_time_universe(data, x)))(d))
        for d in dates
    }


def net_equity(data: dict, sched: dict) -> tuple[pd.Series, pd.DataFrame]:
    """$5k through the daily book's simulator: formed at the close, traded at the next open."""
    names = sorted(set().union(*[s.index for s in sched.values()]))
    idx = data["adj"].index
    targets = pd.DataFrame(0.0, index=idx, columns=names)
    dates = sorted(sched)
    for i, d in enumerate(dates):
        end = dates[i + 1] if i + 1 < len(dates) else idx[-1] + pd.Timedelta(days=1)
        w = sched[d] / sched[d].sum()
        targets.loc[(idx >= d) & (idx < end), w.index] = w.to_numpy()
    targets = targets[targets.index >= dates[0]]
    closes = data["adj"].loc[targets.index, names]
    opens = data["adj_open"].loc[targets.index, names]
    res = simulate(targets, opens, closes, CAPITAL, ExecutionSettings(), ibkr_costs("tiered", 5.0))
    return res.equity, res.trades


def holdings_history(fills: pd.DataFrame, closes: pd.DataFrame, equity: pd.Series) -> pd.DataFrame:
    """Daily positions rebuilt from the simulator's fills: one row per (date, ticker) held, with
    shares, close, value and weight (% of equity). Fills happen at the open, so a day's close
    already includes that day's trades."""
    cols = ["date", "ticker", "shares", "price", "value", "weight"]
    if fills.empty:
        return pd.DataFrame(columns=cols)
    qty = fills.pivot_table(index="date", columns="symbol", values="quantity", aggfunc="sum")
    shares = qty.reindex(equity.index).fillna(0.0).cumsum()
    px = closes.reindex(index=equity.index, columns=shares.columns).ffill()
    s = shares.stack()
    s = s[s.abs() > 1e-9]
    out = pd.DataFrame(
        {
            "date": s.index.get_level_values(0),
            "ticker": s.index.get_level_values(1),
            "shares": s.to_numpy(),
            "price": px.stack().reindex(s.index).to_numpy(),
        }
    )
    out["value"] = out["shares"] * out["price"]
    out["weight"] = out["value"] / equity.reindex(out["date"]).to_numpy()
    return out[cols]


def picks_table(data: dict, lookback: int, skip: int, n: int, top: int = 20) -> pd.DataFrame:
    """Each formation's ranking: the `top` names by momentum within the point-in-time universe,
    with name, market cap and whether the rule bought it (rank <= n). Same ordering as
    `schedules`, so "selected" matches what the portfolio holds."""
    mom = momentum(data["adj"], lookback, skip)
    rows = []
    for d in data["ends"]:
        m = mom.loc[d].reindex(point_in_time_universe(data, d)).dropna()
        if len(m) < n * 2:
            continue
        caps = data["caps"][data["caps"]["date"] == d].drop_duplicates("ticker").set_index("ticker")
        for rank, (t, v) in enumerate(m.nlargest(top).items(), 1):
            rows.append(
                {
                    "formation": d,
                    "rank": rank,
                    "ticker": t,
                    "name": caps["name"].get(t),
                    "momentum": v,
                    "market_cap": caps["market_cap"].get(t),
                    "selected": rank <= n,
                }
            )
    return pd.DataFrame(rows)


HOW_IT_WORKS = """**Rule** (fixed before the test; nothing tuned):
1. At each month-end close, take the **200 largest US companies by market cap on that date**
   (point-in-time, including companies later delisted; one share class per company).
2. Score each by **{sig} momentum**: the price return from {lb_m} months ago to 1 month ago.
   The most recent month is skipped because very short-term winners tend to reverse.
3. Buy the **top {n}, equal weight** ({pct:.0%} each), at the **next day's open**.
4. Next month-end, re-rank: names that fell out of the top {n} are sold, new ones bought.
5. **Between month-ends the target stays {pct:.0%} each**, checked every day: a position that
   drifts more than 2 percentage points away (the rebalance band) is traded back to {pct:.0%}
   at the next open. Winners get trimmed and losers topped up, which is most of the
   {trades_yr:.0f} trades a year.

**Accounting:** $5,000 start, IBKR Pro Tiered commissions, 5 bps slippage per fill,
fractional shares, split-adjusted prices without dividends. (The "no costs" rows in the
report instead let weights drift all month, so they differ slightly in rebalancing too.)
"""


def winner_capture(data: dict, sched: dict, start: pd.Timestamp) -> pd.DataFrame:
    """The period's biggest winners among companies that were ever in the universe: did the
    strategy hold them, from when, and how much of their rise came before it bought?"""
    ever = set().union(*[point_in_time_universe(data, d) for d in data["ends"] if d >= start])
    adj = data["adj"].loc[start:, sorted(ever)]
    listings = {t: current_listing(adj[t]) for t in adj.columns}
    total = pd.Series(
        {t: s.iloc[-1] / s.iloc[0] - 1 for t, s in listings.items() if len(s) > 1}
    ).dropna()
    rows = []
    for t in total.nlargest(N_WINNERS).index:
        held = [d for d, w in sched.items() if t in w.index]
        px = listings[t]
        first = min(held) if held else None
        before = (px.loc[:first].iloc[-1] / px.iloc[0] - 1) if first is not None else np.nan
        rows.append(
            {
                "ticker": t,
                "total rise": total[t],
                "months held": len(held),
                "months in test": len([d for d in sched if d >= start]),
                "first bought": first.date() if first is not None else "never",
                "rise before first buy": before,
            }
        )
    return pd.DataFrame(rows).set_index("ticker")


def worst_picks(data: dict, sched: dict, k: int = 10) -> pd.DataFrame:
    rows = []
    dates = sorted(sched)
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        px = data["adj"].loc[d:nxt]
        for t in sched[d].index:
            s = px[t].dropna()
            if len(s) > 1:
                rows.append(
                    {
                        "month": d.date(),
                        "ticker": t,
                        "next-month return": s.iloc[-1] / s.iloc[0] - 1,
                    }
                )
    df = pd.DataFrame(rows)
    return df.nsmallest(k, "next-month return").set_index(["month", "ticker"])


def _stats(eq: pd.Series, spy: pd.Series) -> dict:
    s = A.equity_stats(eq, spy)
    return {
        "CAGR": s["CAGR"],
        "Sharpe": s["Sharpe"],
        "max DD": s["max DD"],
        "beta": s.get("beta"),
        "total": s["total return"],
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save the $5k net curves as dashboard runs")
    args = p.parse_args()
    pd.set_option("display.width", 250)
    data = M.pit_data()
    adj = data["adj"]
    today_uni = point_in_time_universe(data, data["ends"][-1])

    rows, curves = [], {}
    for sig, (lb, sk) in SIGNALS.items():
        first = None
        for n in SIZES:
            sched = schedules(data, lb, sk, n)
            first = min(sched)
            gross = M.run_portfolio(data["returns"], sched)
            net, trades = net_equity(data, sched)
            spy = adj["SPY"][adj.index >= first].dropna()
            label = f"momentum {sig}, top {n}"
            curves[label] = (net, trades, sig, n)
            costs = trades["commission"].sum() if len(trades) else 0.0
            rows.append(
                {"portfolio": label, "from": first.date()}
                | {f"gross {k}": v for k, v in _stats(gross, spy).items()}
                | {f"$5k net {k}": v for k, v in _stats(net, spy).items()}
                | {
                    "costs $": costs,
                    "trades/yr": len(trades) / ((adj.index[-1] - first).days / 365.25),
                }
            )
        dates = sorted(schedules(data, lb, sk, SIZES[0]))
        uni = M.run_portfolio(data["returns"], universe_schedule(data, dates))
        spy = adj["SPY"][adj.index >= first].dropna()
        qqq = adj["QQQ"][adj.index >= first].dropna()
        rows.append(
            {
                "portfolio": f"benchmark: 200 largest, equal weight (from {first.date()})",
                "from": first.date(),
            }
            | {f"gross {k}": v for k, v in _stats(uni, spy).items()}
        )
        rows.append(
            {"portfolio": f"benchmark: SPY (from {first.date()})", "from": first.date()}
            | {f"gross {k}": v for k, v in _stats(spy / spy.iloc[0], spy).items()}
        )
        rows.append(
            {"portfolio": f"benchmark: QQQ (from {first.date()})", "from": first.date()}
            | {f"gross {k}": v for k, v in _stats(qqq / qqq.iloc[0], spy).items()}
        )
        # survivorship contrast: the same rule on TODAY's 200 largest companies
        surv = schedules(data, lb, sk, SIZES[0], universe_at=lambda d: today_uni)
        surv_eq = M.run_portfolio(data["returns"], surv)
        surv_uni = M.run_portfolio(
            data["returns"], universe_schedule(data, dates, lambda d: today_uni)
        )
        rows.append(
            {
                "portfolio": f"SURVIVORSHIP: momentum {sig} top 10 on TODAY's 200 largest",
                "from": first.date(),
            }
            | {f"gross {k}": v for k, v in _stats(surv_eq, spy).items()}
        )
        rows.append(
            {"portfolio": "SURVIVORSHIP: TODAY's 200 largest, equal weight", "from": first.date()}
            | {f"gross {k}": v for k, v in _stats(surv_uni, spy).items()}
        )

    table = pd.DataFrame(rows).set_index("portfolio")
    fmt = table.copy()
    for c in fmt.columns:
        if any(k in c for k in ("CAGR", "max DD", "total")):
            fmt[c] = fmt[c].map(lambda v: f"{v:.1%}" if pd.notna(v) else "-")
        elif c not in ("from",):
            fmt[c] = fmt[c].map(lambda v: f"{v:,.2f}" if pd.notna(v) else "-")
    print("=== momentum among the 200 largest companies (point-in-time), price only ===")
    print(fmt.to_string())

    sched = schedules(data, *SIGNALS["12-1"], 10)
    start = min(sched)
    print(
        f"\n=== the {N_WINNERS} biggest winners since {start.date()} among companies ever in "
        "the top 200: did momentum 12-1 top 10 catch them? ==="
    )
    wc = winner_capture(data, sched, start)
    wc["total rise"] = wc["total rise"].map("{:.0%}".format)
    wc["rise before first buy"] = wc["rise before first buy"].map(
        lambda v: "-" if pd.isna(v) else f"{v:.0%}"
    )
    print(wc.to_string())
    print("\n=== its 10 worst monthly picks ===")
    print(worst_picks(data, sched).map("{:.1%}".format).to_string())

    if args.save:
        marks = adj.ffill().iloc[-1].dropna().to_dict()
        for name, (eq, fills, sig, n) in curves.items():
            lb, sk = SIGNALS[sig]
            meta = {
                "strategy": "large-cap momentum (point-in-time)",
                "params": {"signal": sig, "top": n, "universe": UNIVERSE, "capital": CAPITAL},
                "oos_start": "2025-01-01",
                "chart": "daily",
                "how_it_works": HOW_IT_WORKS.format(
                    sig=sig,
                    lb_m=lb // 21,
                    n=n,
                    pct=1 / n,
                    trades_yr=len(fills) / ((eq.index[-1] - eq.index[0]).days / 365.25),
                ),
                "caveats": [
                    "Price only (no dividends).",
                    "About 3-4 years of test data, one bull market.",
                    "4 pre-registered variants (backtest/winners.py).",
                    "Weight-based rebalancing: 'trades' are FIFO lot slices, not discrete signals.",
                ],
                "benchmark": "SPY (price only)",
            }
            spy = adj["SPY"].reindex(eq.index).ffill()
            tables = {
                "holdings": holdings_history(fills, adj, eq),
                "picks": picks_table(data, lb, sk, n),
            }
            trips = A.round_trips(fills, marks)
            path = bundle.save_run(f"winners: {name}, $5k net", eq, trips, meta, spy, tables)
            print("saved", path.name)


if __name__ == "__main__":
    main()
