"""Do the biggest companies make the best portfolio? Top 10 / 50 / 100 vs S&P 500 and Nasdaq-100.

    uv run python -m horizon_trader.backtest.megacap [--save]

Part A (2008-2026, real index funds, dividends included, fund fees included): SPY (S&P 500),
OEF (S&P 100), XLG (S&P 500 Top 50), QQQ (Nasdaq-100), MGC (Vanguard Mega Cap) and RSP
(S&P 500 equal weight). Funds can't have hindsight: they held what their index held.

Part B (Oct 2021 - Sep 2026, built from Massive data, price only for everything): at the end
of each month, rank US common stocks by market cap AS OF THAT DATE (Massive ticker overview,
point-in-time shares outstanding; the 300 most-traded stocks are the candidates, which always
include the largest companies), keep one share class per company, and hold the top 10 / 50 /
100 for the next month, weighted by market cap or equally. Compared with SPY and QQQ over the
same days, also price only. Plus a hindsight contrast: TODAY's top 10 bought in Oct 2021,
which is what "just own the biggest companies" looks like when picked with the benefit of
knowing who won.

Nothing is tuned: N = 10 / 50 / 100 is the owner's question, monthly rebalancing is standard.
No trading costs (these are investment portfolios; see the note for what monthly rebalancing
of 100 names would cost at $5k).
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.data import massive, massive_ref
from horizon_trader.data.massive_ref import API, _http_get
from horizon_trader.data.store import load_bars
from horizon_trader.intraday import features as F

ETFS = {
    "SPY": "S&P 500",
    "OEF": "S&P 100",
    "XLG": "S&P 500 Top 50",
    "QQQ": "Nasdaq-100",
    "MGC": "Vanguard Mega Cap",
    "RSP": "S&P 500 equal weight",
}
TOP_NS = (10, 50, 100)
CANDIDATES = 300
BENCHMARKS = ("SPY", "QQQ", "OEF", "XLG", "RSP")


# ---------------------------------------------------------------- part A: index funds


def part_a(start: str = "2008-01-01") -> tuple[pd.DataFrame, pd.DataFrame]:
    closes = load_bars(list(ETFS))["close"].loc[start:].dropna()
    rows = []
    for t in ETFS:
        eq = closes[t] / closes[t].iloc[0]
        s = A.equity_stats(eq, closes["SPY"])
        rows.append(
            {
                "fund": f"{t} ({ETFS[t]})",
                "CAGR": s["CAGR"],
                "Sharpe": s["Sharpe"],
                "max DD": s["max DD"],
                "vol": s["vol"],
                "beta to SPY": s.get("beta"),
                "$10k becomes": 10_000 * eq.iloc[-1],
            }
        )
    yearly = closes.resample("YE").last().pct_change()
    yearly.iloc[0] = closes.resample("YE").last().iloc[0] / closes.iloc[0] - 1
    yearly.index = yearly.index.year
    return pd.DataFrame(rows).set_index("fund"), yearly


# ---------------------------------------------------------------- part B: point-in-time top N


def _cap_path():
    return massive_ref.ref_path("market_caps")


def market_caps(pairs: list[tuple[str, date]], threads: int = 16) -> pd.DataFrame:
    """Point-in-time market cap per (ticker, date) from Massive's ticker overview, cached."""
    path = _cap_path()
    cached = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=["ticker", "date"])
    have = set(zip(cached["ticker"], pd.to_datetime(cached["date"]).dt.date, strict=True))
    todo = [p for p in pairs if p not in have]

    def fetch(p):
        tk, d = p
        try:
            r = _http_get(f"{API}/v3/reference/tickers/{tk}?date={d}").get("results", {})
        except Exception:  # noqa: BLE001  (a missing ticker/date is just "no cap")
            r = {}
        return {
            "ticker": tk,
            "date": pd.Timestamp(d),
            "market_cap": r.get("market_cap"),
            "cik": r.get("cik"),
            "name": r.get("name"),
        }

    if todo:
        print(f"  fetching {len(todo):,} point-in-time market caps", flush=True)
        with ThreadPoolExecutor(max_workers=threads) as pool:
            new = pd.DataFrame(list(pool.map(fetch, todo)))
        cached = pd.concat([cached, new], ignore_index=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        cached.to_parquet(path, index=False)
    out = cached.assign(date=pd.to_datetime(cached["date"]))
    wanted = {(t, pd.Timestamp(d)) for t, d in pairs}
    return out[[(t, d) in wanted for t, d in zip(out["ticker"], out["date"], strict=True)]]


def month_ends(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(index, index=index)
    return list(s.groupby(index.to_period("M")).max())


def top_n(caps: pd.DataFrame, n: int) -> pd.Series:
    """{ticker: market cap} of the n largest companies (one share class per company)."""
    c = caps.dropna(subset=["market_cap"]).sort_values("market_cap", ascending=False)
    key = c["cik"].fillna(c["ticker"])  # GOOGL/GOOG and BRK.A/BRK.B share a CIK
    c = c[~key.duplicated()]
    return c.head(n).set_index("ticker")["market_cap"]


def hold_period(returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Daily portfolio growth over one holding period: buy the weights, let them drift.
    A stock that stops trading (acquired, delisted) is held as cash from its last price."""
    r = returns.reindex(columns=weights.index).fillna(0.0)
    value = (1 + r).cumprod().mul(weights / weights.sum(), axis=1).sum(axis=1)
    return value


def run_portfolio(returns: pd.DataFrame, schedule: dict[pd.Timestamp, pd.Series]) -> pd.Series:
    """Chain monthly holding periods; each starts the day after its formation date."""
    dates = sorted(schedule)
    equity, level = [], 1.0
    for i, d in enumerate(dates):
        end = dates[i + 1] if i + 1 < len(dates) else returns.index[-1]
        period = returns[(returns.index > d) & (returns.index <= end)]
        if period.empty:
            continue
        growth = hold_period(period, schedule[d])
        equity.append(level * growth)
        level *= growth.iloc[-1]
    first = pd.Series([1.0], index=[dates[0]])
    return pd.concat([first, *equity])


def pit_data() -> dict:
    """Point-in-time panels shared by the mega-cap studies: split-adjusted (price-only) opens,
    closes and daily returns for every US common stock plus the benchmark ETFs, month-end
    formation dates, and each month-end's market caps for the most-traded candidates."""
    days = massive.local_days("day")
    common = massive_ref.load_common_tickers()
    panels = F.load_daily_panels(days, common | set(BENCHMARKS))
    factor = F.split_factors(
        panels["close"].index, panels["close"].columns, massive_ref.load_splits()
    )
    adj = panels["close"] * factor
    dollar_vol = (panels["close"] * panels["volume"]).rolling(21, min_periods=10).mean()
    stock_cols = [c for c in adj.columns if c in common]
    ends = month_ends(adj.index)[:-1]  # the last month-end has no holding period after it
    pairs = []
    for d in ends:
        cands = dollar_vol.loc[d, stock_cols].nlargest(CANDIDATES).index
        pairs += [(t, d.date()) for t in cands]
    return {
        "adj": adj,
        "adj_open": panels["open"] * factor,
        "returns": adj.pct_change(fill_method=None),
        "dollar_vol": dollar_vol,
        "stock_cols": stock_cols,
        "ends": ends,
        "caps": market_caps(pairs),
    }


def part_b():
    data = pit_data()
    adj, returns, dollar_vol = data["adj"], data["returns"], data["dollar_vol"]
    stock_cols, ends, caps = data["stock_cols"], data["ends"], data["caps"]

    schedules = {n: {"cap": {}, "equal": {}} for n in TOP_NS}
    for d in ends:
        c = caps[caps["date"] == d]
        for n in TOP_NS:
            top = top_n(c, n)
            schedules[n]["cap"][d] = top.astype(float)
            schedules[n]["equal"][d] = pd.Series(1.0, index=top.index)
    curves = {}
    for n in TOP_NS:
        for w in ("cap", "equal"):
            curves[f"top {n}, {w}-weighted"] = run_portfolio(returns, schedules[n][w])
    start = ends[0]
    for b in BENCHMARKS:
        px = adj[b][adj.index >= start].dropna()
        curves[f"{b} ({ETFS[b]}), price only"] = px / px.iloc[0]
    # hindsight contrast: today's 10 largest, bought at the start and held
    today = top_n(
        market_caps(
            [
                (t, ends[-1].date())
                for t in dollar_vol.iloc[-1][stock_cols].nlargest(CANDIDATES).index
            ]
        ),
        10,
    )
    curves["HINDSIGHT: today's top 10, bought Oct 2021"] = run_portfolio(
        returns[returns.index <= returns.index[-1]], {start: pd.Series(1.0, index=today.index)}
    )
    return curves, schedules, today


def stats_table(curves: dict[str, pd.Series], benchmark: pd.Series) -> pd.DataFrame:
    rows = []
    for name, eq in curves.items():
        s = A.equity_stats(eq, benchmark)
        yearly = eq.resample("YE").last()
        rows.append(
            {
                "portfolio": name,
                "CAGR": s["CAGR"],
                "Sharpe": s["Sharpe"],
                "max DD": s["max DD"],
                "vol": s["vol"],
                "beta to SPY": s.get("beta"),
                "total return": s["total return"],
                "worst year": yearly.pct_change().min(),
            }
        )
    return pd.DataFrame(rows).set_index("portfolio")


def _fmt(df: pd.DataFrame) -> str:
    out = df.copy()
    for c in out.columns:
        if c in ("CAGR", "max DD", "vol", "total return", "worst year") or isinstance(
            c, (int, np.integer)
        ):
            out[c] = out[c].map(lambda v: f"{v:.1%}" if pd.notna(v) else "-")
        elif c == "$10k becomes":
            out[c] = out[c].map("${:,.0f}".format)
        else:
            out[c] = out[c].map(lambda v: f"{v:.2f}" if pd.notna(v) else "-")
    return out.to_string()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--save", action="store_true", help="save the curves as dashboard runs")
    args = p.parse_args()
    pd.set_option("display.width", 250)

    a, yearly = part_a()
    print("=== Part A: index funds, Jan 2008 - Sep 2026 (dividends and fund fees included) ===")
    print(_fmt(a))
    print("\ncalendar-year returns:")
    print(_fmt(yearly))

    curves, schedules, today = part_b()
    spy = curves["SPY (S&P 500), price only"]
    first, last = spy.index[0].date(), spy.index[-1].date()
    print(f"\n=== Part B: point-in-time top N by market cap, {first} .. {last} (price only) ===")
    print(_fmt(stats_table(curves, spy)))
    print(f"\ntoday's 10 largest (hindsight set): {', '.join(today.index)}")
    first_d = min(schedules[10]["cap"])
    print(f"10 largest on {first_d.date()}: {', '.join(schedules[10]['cap'][first_d].index)}")
    changes = [
        len(set(schedules[10]["cap"][b].index) - set(schedules[10]["cap"][a].index))
        for a, b in zip(
            sorted(schedules[10]["cap"]), sorted(schedules[10]["cap"])[1:], strict=False
        )
    ]
    print(f"top-10 membership changes: {sum(changes)} over {len(changes)} month-ends")

    if args.save:
        empty = pd.DataFrame(columns=bundle.TRADE_COLUMNS)
        for name, eq in curves.items():
            meta = {
                "strategy": "mega-cap portfolios",
                "oos_start": "2024-01-01",
                "chart": "daily",
                "caveats": [
                    "Price only (no dividends) for every Part B curve.",
                    "Monthly rebalancing, no trading costs.",
                ],
            }
            path = bundle.save_run(
                f"megacap: {name}",
                5_000.0 * eq,
                empty,
                meta,
                5_000.0 * spy.reindex(eq.index).ffill(),
            )
            print("saved", path.name)


if __name__ == "__main__":
    main()
