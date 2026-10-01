"""Copy-trading Congress: buy what members disclose, when it becomes public. Does it beat SPY?

    uv run python -m horizon_trader.congress.event_study [--save]

Pre-registered 2026-09-28, before running:
  events     every disclosed PURCHASE by a member of Congress with a US ticker that has
             Massive daily bars (stocks and ETFs; option purchases are copied as a stock buy
             in the underlying; bonds, munis, crypto and "other" are dropped), filed
             2021-10 .. 2026-09. One event per (filer, ticker, filing date). The dataset's
             executive-branch filers (cabinet officials, OGE forms) are reported as a
             separate group, not in A / B.
  timing     honest: known after the filing date, bought at the next regular open.
             lookahead (for contrast only): bought at the next open after the TRADE date,
             which a copier can't do; many "Pelosi tracker" backtests do this implicitly.
  returns    open-to-close, split-adjusted, price only, 5 / 20 / 60 / 120 trading days, minus
             SPY over the same days. t-stats cluster by entry week.
  portfolios equal weight across the names held, daily targets through the daily book's
             simulator (IBKR Pro Tiered, 5 bps):
             A. all of Congress, each purchase held 60 trading days          ($100k)
             B. purchases of $250k or more only, held 60 days                ($100k)
             C. Pelosi (her filings, nearly all her husband's trades): held until she
                discloses a sale of it, or 252 trading days; each name at most 20% ($5k)
             A* and C*: the same with lookahead timing.
             vs SPY and QQQ over the same days; plus the live ETFs that do this (NANC =
             Democrats' disclosed buys, KRUZ = Republicans'), since their 2023 launch.
Known limits: amounts are ranges, so trades are equal-weighted, not size-weighted. Options
are copied as stock (Pelosi's calls were leveraged; a stock copy understates both gains and
risk). The dataset parses free-text filings; about 20% of rows have no ticker.
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.backtest import winners as W
from horizon_trader.backtest.sim import simulate
from horizon_trader.config import ExecutionSettings
from horizon_trader.congress import archive
from horizon_trader.datasources import massive, massive_ref
from horizon_trader.datasources.store import load_bars
from horizon_trader.execution.costs import ZERO_COSTS, ibkr_costs
from horizon_trader.intraday import features as F
from horizon_trader.social.event_study import clustered_t, listing_start

BENCH = ("SPY", "QQQ")
HORIZONS = (5, 20, 60, 120)
START = pd.Timestamp("2021-10-04")
DROP_TYPES = {
    "Municipal Security",
    "GS",
    "Corporate Bond",
    "Commodities/Futures Contract",
    "OT",
    "HN",
    "CT",
    "Cryptocurrency",
    "AB",
    "OL",
    "PS",
    "DBC",
}
PELOSI = "house_nancy_pelosi"
HOLD, PELOSI_MAX_HOLD, BIG = 60, 252, 250_001


# ---------------------------------------------------------------- data


def load_prices(tickers: set[str]) -> dict:
    days = [d for d in massive.local_days("day") if d >= date(2021, 9, 1)]
    panels = F.load_daily_panels(days, tickers | set(BENCH))
    factor = F.split_factors(
        panels["close"].index, panels["close"].columns, massive_ref.load_splits()
    )
    return {"adj": panels["close"] * factor, "adj_open": panels["open"] * factor}


def signal_rows(dates: pd.Series, days: pd.DatetimeIndex) -> np.ndarray:
    """Last trading day on or before each date: the information is in hand by that day's end,
    so a copier trades at the next open (row + 1)."""
    return days.searchsorted(pd.DatetimeIndex(dates), side="right") - 1


def purchases(trades: pd.DataFrame, px: dict) -> pd.DataFrame:
    days = px["adj"].index
    have = set(px["adj"].columns) - set(BENCH)
    starts = listing_start(px["adj"])
    b = trades[
        (trades["transaction_type"] == "Purchase")
        & trades["ticker"].isin(have)
        & ~trades["asset_type"].isin(DROP_TYPES)
        & (trades["filing_date"] >= START)
    ].copy()
    b = b.dropna(subset=["transaction_date", "filing_date"])
    b = b[b["transaction_date"] <= b["filing_date"]]
    b = b.drop_duplicates(["filer_id", "ticker", "filing_date"])
    for kind, col in (("row", "filing_date"), ("row_trade", "transaction_date")):
        b[kind] = signal_rows(b[col], days)
    b = b[(b["row_trade"] >= 0) & (b["row"] + 1 < len(days))]
    first = b["ticker"].map(starts)
    return b[days[(b["row_trade"] + 1).clip(upper=len(days) - 1)] >= first].reset_index(drop=True)


def sales(trades: pd.DataFrame) -> pd.DataFrame:
    s = trades[trades["transaction_type"].str.startswith("Sale", na=False)]
    return s.dropna(subset=["ticker", "filing_date", "transaction_date"])


# ---------------------------------------------------------------- event study


def forward(ev: pd.DataFrame, px: dict, row_col: str, horizons=HORIZONS) -> pd.DataFrame:
    """Return from the open after `row_col` to the close h-1 days later, minus SPY's."""
    adj, opn = px["adj"].ffill(), px["adj_open"]
    n = len(adj)
    entry = ev[row_col].to_numpy() + 1
    cols = {t: adj.columns.get_loc(t) for t in set(ev["ticker"]) | set(BENCH)}
    ci = np.array([cols[t] for t in ev["ticker"]])
    spy = cols["SPY"]
    A_, O_ = adj.to_numpy(), opn.to_numpy()
    out = {}
    for h in horizons:
        end = entry + h - 1
        ok = end < n
        e, x = np.where(ok, entry, 0), np.where(ok, end, 0)
        r = A_[x, ci] / O_[e, ci] - 1
        s = A_[x, spy] / O_[e, spy] - 1
        out[f"ret_{h}d"] = np.where(ok, r, np.nan)
        out[f"xs_{h}d"] = np.where(ok, r - s, np.nan)
    return pd.DataFrame(out, index=ev.index)


def summary(ev: pd.DataFrame, px: dict) -> pd.DataFrame:
    days = px["adj"].index
    cong = ev["branch"] == "congress"
    groups = {
        "all Congress": ev.index[cong],
        "$250k+": ev.index[cong & (ev["amount_range_low"] >= BIG)],
        "$1k-15k": ev.index[cong & (ev["amount_range_high"] <= 15_000)],
        "House": ev.index[ev["chamber"] == "house"],
        "Senate": ev.index[ev["chamber"] == "senate"],
        "Democrats": ev.index[ev["party"] == "D"],
        "Republicans": ev.index[ev["party"] == "R"],
        "Pelosi": ev.index[ev["filer_id"] == PELOSI],
        "executive branch": ev.index[ev["branch"] == "executive"],
    }
    rows = []
    for timing, col in (("filing (copyable)", "row"), ("trade (lookahead)", "row_trade")):
        f = forward(ev, px, col)
        week = pd.Series(days[ev[col].to_numpy() + 1], index=ev.index).dt.to_period("W")
        for name, idx in groups.items():
            for h in HORIZONS:
                xs = f.loc[idx, f"xs_{h}d"].dropna()
                rows.append(
                    {
                        "group": name,
                        "entry after": timing,
                        "horizon": f"{h}d",
                        "events": len(xs),
                        "mean vs SPY": xs.mean(),
                        "median vs SPY": xs.median(),
                        "% beat SPY": (xs > 0).mean(),
                        "t (weekly)": clustered_t(xs, week.loc[xs.index]),
                    }
                )
    return pd.DataFrame(rows).set_index(["group", "entry after", "horizon"])


# ---------------------------------------------------------------- portfolios


def held_matrix(ev: pd.DataFrame, days, row_col: str, hold: int) -> pd.DataFrame:
    names = sorted(ev["ticker"].unique())
    held = np.zeros((len(days), len(names)), bool)
    col = {t: i for i, t in enumerate(names)}
    for r, t in zip(ev[row_col].to_numpy(), ev["ticker"], strict=True):
        held[r : r + hold, col[t]] = True
    return pd.DataFrame(held, index=days, columns=names)


def pelosi_held(ev: pd.DataFrame, sells: pd.DataFrame, days, lookahead: bool) -> pd.DataFrame:
    """Held from her disclosed purchase until her next disclosed sale of it (at most
    PELOSI_MAX_HOLD days). Sales count from their filing date (trade date if lookahead)."""
    date_col = "transaction_date" if lookahead else "filing_date"
    row_col = "row_trade" if lookahead else "row"
    s = sells.assign(row=signal_rows(sells[date_col], days))
    names = sorted(ev["ticker"].unique())
    held = pd.DataFrame(False, index=days, columns=names)
    for r, t in zip(ev[row_col], ev["ticker"], strict=True):
        later = s.loc[(s["ticker"] == t) & (s["row"] > r), "row"]
        end = min(int(later.min()) if len(later) else len(days), r + PELOSI_MAX_HOLD)
        held.iloc[r:end, held.columns.get_loc(t)] = True
    return held


def run(held: pd.DataFrame, px: dict, capital: float, costs, max_weight: float = 1.0):
    n = held.sum(axis=1).clip(lower=1)
    w = held.astype(float).div(n, axis=0).clip(upper=max_weight)
    w = w.loc[w.index[w.sum(axis=1) > 0][0] :]
    res = simulate(
        w,
        px["adj_open"].loc[w.index, w.columns],
        px["adj"].loc[w.index, w.columns],
        capital,
        ExecutionSettings(),
        costs,
    )
    return res.equity, res.trades


def portfolios(ev: pd.DataFrame, trades: pd.DataFrame, px: dict) -> tuple[pd.DataFrame, dict]:
    days = px["adj"].index
    pel = ev[ev["filer_id"] == PELOSI]
    cong = ev[ev["branch"] == "congress"]  # the executive branch is reported separately
    pel_sells = sales(trades[trades["filer_id"] == PELOSI])
    specs = {
        "A. all of Congress, 60 days": (held_matrix(cong, days, "row", HOLD), 100_000.0, 1.0),
        "A*. same, LOOKAHEAD (trade date)": (
            held_matrix(cong, days, "row_trade", HOLD),
            100_000.0,
            1.0,
        ),
        "B. $250k+ purchases, 60 days": (
            held_matrix(cong[cong["amount_range_low"] >= BIG], days, "row", HOLD),
            100_000.0,
            1.0,
        ),
        "C. Pelosi, until her sale / 1 year": (
            pelosi_held(pel, pel_sells, days, False),
            5_000.0,
            0.2,
        ),
        "C*. Pelosi, LOOKAHEAD (trade date)": (
            pelosi_held(pel, pel_sells, days, True),
            5_000.0,
            0.2,
        ),
    }
    rows, curves = [], {}
    for name, (held, capital, cap) in specs.items():
        net, fills = run(held, px, capital, ibkr_costs("tiered", 5.0), cap)
        gross, _ = run(held, px, capital, ZERO_COSTS, cap)
        curves[name] = (net, fills, capital)
        spy = px["adj"]["SPY"].reindex(net.index)
        for kind, eq in (("net", net), ("gross", gross)):
            s = A.equity_stats(eq, spy)
            rows.append(
                {
                    "portfolio": name,
                    "costs": kind,
                    "from": eq.index[0].date(),
                    "names held (avg)": held.loc[eq.index].sum(axis=1).mean(),
                    "CAGR": s["CAGR"],
                    "Sharpe": s["Sharpe"],
                    "max DD": s["max DD"],
                    "beta": s.get("beta"),
                    "alpha/yr": s.get("alpha/yr"),
                }
            )
    start = min(eq.index[0] for eq, _, _ in curves.values())
    for b in BENCH:
        eq = px["adj"][b].loc[start:]
        s = A.equity_stats(eq / eq.iloc[0], px["adj"]["SPY"].loc[start:])
        rows.append(
            {
                "portfolio": f"benchmark: {b}",
                "costs": "gross",
                "from": start.date(),
                "CAGR": s["CAGR"],
                "Sharpe": s["Sharpe"],
                "max DD": s["max DD"],
                "beta": s.get("beta"),
                "alpha/yr": s.get("alpha/yr"),
            }
        )
    return pd.DataFrame(rows).set_index(["portfolio", "costs"]), curves


def live_etfs() -> pd.DataFrame:
    """NANC (live copy-trading ETF, dividends included via yfinance) vs SPY / QQQ. KRUZ, the
    Republican twin, returns no data from yfinance (apparently delisted)."""
    close = load_bars(["NANC", "SPY", "QQQ"])["close"].dropna()
    rows = []
    for t in close.columns:
        eq = close[t] / close[t].iloc[0]
        s = A.equity_stats(eq, close["SPY"])
        rows.append(
            {
                "fund": t,
                "from": close.index[0].date(),
                "CAGR": s["CAGR"],
                "total": s["total return"],
                "Sharpe": s["Sharpe"],
                "max DD": s["max DD"],
                "beta": s.get("beta"),
                "alpha/yr": s.get("alpha/yr"),
            }
        )
    return pd.DataFrame(rows).set_index("fund")


def _pct(df: pd.DataFrame) -> pd.DataFrame:
    out = df.astype(object).copy()
    for c in df.columns:
        if c in ("Sharpe", "beta", "t (weekly)", "names held (avg)"):
            out[c] = df[c].map(lambda v: "-" if pd.isna(v) else f"{v:.2f}")
        elif c in ("events",):
            out[c] = df[c].map(lambda v: f"{v:,.0f}")
        elif c != "from":
            out[c] = df[c].map(lambda v: "-" if pd.isna(v) else f"{v:+.1%}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true")
    args = p.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 200)
    trades = archive.load()
    px = load_prices(set(trades["ticker"].dropna()))
    ev = purchases(trades, px)
    lag = (ev["filing_date"] - ev["transaction_date"]).dt.days
    print(
        f"{len(ev):,} purchase events by {ev['filer_id'].nunique()} filers, filed "
        f"{ev['filing_date'].min():%Y-%m-%d} .. {ev['filing_date'].max():%Y-%m-%d}; "
        f"trade -> public: median {lag.median():.0f} days, p90 {lag.quantile(0.9):.0f}\n"
    )

    s = summary(ev, px)
    print("=== returns vs SPY after each disclosed purchase ===")
    print(_pct(s).to_string(), "\n")

    print("=== portfolios ===")
    table, curves = portfolios(ev, trades, px)
    print(_pct(table).to_string(), "\n")

    print("=== the live copy-trading ETFs (dividends included) ===")
    print(_pct(live_etfs()).to_string())

    if args.save:
        marks = px["adj"].ffill().iloc[-1].dropna().to_dict()
        for name, (eq, fills, capital) in curves.items():
            meta = {
                "strategy": "copy-trade Congress (STOCK Act disclosures)",
                "params": {"variant": name, "capital": capital},
                "chart": "daily",
                "caveats": [
                    "Equal-weighted; disclosed amounts are ranges.",
                    "Options copied as stock in the underlying.",
                    "LOOKAHEAD rows use trade dates a copier can't know.",
                ],
                "benchmark": "SPY (price only)",
            }
            path = bundle.save_run(
                f"congress: {name}",
                eq,
                A.round_trips(fills, marks),
                meta,
                px["adj"]["SPY"].reindex(eq.index).ffill(),
                {"holdings": W.holdings_history(fills, px["adj"], eq)},
            )
            print("saved", path.name)


if __name__ == "__main__":
    main()
