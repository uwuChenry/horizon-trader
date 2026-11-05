"""Saved backtest bundles (data/results): performance, trades, costs, honesty, holdings.

Every number comes from backtest/analytics.py (tested), so the dashboard and the CLI reports
can't disagree. Create bundles with --save on the backtest commands.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.dashboard import holdings_view as H
from horizon_trader.dashboard.bars import trade_bars
from horizon_trader.dashboard.serialize import clean, points, seconds, table

router = APIRouter(prefix="/api/backtests")

META_KEYS = [
    "name", "strategy", "created", "start", "end", "git_commit", "git_dirty", "caveats",
    "params", "benchmark", "oos_start", "costs_description", "chart", "how_it_works",
]  # fmt: skip
DIMENSIONS = [
    "exit_reason", "side label", "weekday", "entry time", "year", "holding (h)",
    "relative volume", "rank", "symbol (top 12)",
]  # fmt: skip
TRADE_COLUMNS = [
    "entry_time", "exit_time", "symbol", "side label", "qty", "entry_px", "exit_px", "gross",
    "costs", "pnl", "R", "exit_reason", "mae_R", "mfe_R", "relvol", "rank", "stop_px",
]  # fmt: skip


@lru_cache(maxsize=16)
def load(run_id: str) -> bundle.Run:
    try:
        return bundle.load_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, f"No run {run_id}") from exc


@lru_cache(maxsize=256)
def headline(run_id: str) -> dict:
    run = load(run_id)
    s = A.equity_stats(run.equity)
    return {
        "CAGR": s["CAGR"],
        "Sharpe": s["Sharpe"],
        "max DD": s["max DD"],
        "trades": len(run.trades),
    }


def benchmark_equity(run: bundle.Run) -> pd.Series | None:
    """Benchmark rescaled to the strategy's starting equity (buy and hold)."""
    if run.benchmark is None or run.benchmark.dropna().empty:
        return None
    b = run.benchmark.reindex(run.equity.index).ffill().bfill()
    return b / b.iloc[0] * run.equity.iloc[0]


def add_dimensions(t: pd.DataFrame) -> pd.DataFrame:
    """Derived columns to slice trades by."""
    t = t.copy()
    t["side label"] = t["side"].map({1: "long", -1: "short"})
    t["result"] = np.where(t["pnl"] > 0, "win", "loss")
    entry = t["entry_time"]
    t["weekday"] = pd.Categorical(
        entry.dt.day_name().str[:3], ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ordered=True
    )
    t["year"] = entry.dt.year
    intraday = (t["exit_time"] - t["entry_time"]).max() < pd.Timedelta(days=1)
    if intraday:
        t["entry time"] = entry.dt.floor("30min").dt.strftime("%H:%M")
    top = t["symbol"].value_counts().head(12).index
    t["symbol (top 12)"] = t["symbol"].where(t["symbol"].isin(top), "other")
    relvol = pd.to_numeric(t["relvol"], errors="coerce") if "relvol" in t else None
    if relvol is not None and relvol.notna().any():  # ETF runs have no relative volume
        t["relative volume"] = pd.cut(relvol, [1, 2, 3, 5, 10, 30, np.inf], right=False)
    held = (t["exit_time"] - t["entry_time"]) / pd.Timedelta(hours=1)
    edges = [0, 1, 3, 6.5, 24, 24 * 7, 24 * 30, np.inf] if not intraday else [0, 0.5, 1, 2, 4, 7]
    t["holding (h)"] = pd.cut(held, edges, right=False)
    return t


def histogram(values: pd.Series, width: float) -> dict:
    v = values.dropna().to_numpy(dtype=float)
    if not len(v):
        return {"edges": [], "counts": []}
    lo, hi = np.floor(v.min() / width) * width, np.ceil(v.max() / width) * width + width
    counts, edges = np.histogram(v, np.arange(lo, hi + width / 2, width))
    return {"edges": edges.round(6).tolist(), "counts": counts.tolist()}


def daily_cumsum(times: pd.Series, values: pd.Series) -> pd.Series:
    """Cumulative sum by exit day: chart time axes need one point per strictly rising time."""
    days = pd.DatetimeIndex(times).tz_localize(None) if times.dt.tz is not None else times
    s = pd.Series(values.to_numpy(), index=pd.DatetimeIndex(days).normalize())
    return s.groupby(level=0).sum().cumsum()


@router.get("")
def runs() -> dict:
    listed = bundle.list_runs()
    rows = []
    for r in listed.itertuples():
        try:
            stats = headline(r.run_id)
        except Exception:  # a broken bundle must not hide the others
            stats = {}
        rows.append(
            {
                "run_id": r.run_id,
                "name": r.name,
                "strategy": r.strategy,
                "created": r.created,
                "start": r.start,
                "end": r.end,
                "holdings": bundle.has_table(r.run_id, "holdings"),
            }
            | stats
        )
    return {"runs": clean(rows)}


@router.get("/compare")
def compare(ids: str = Query(..., description="comma-separated run ids, up to 6")) -> dict:
    out = []
    for rid in ids.split(",")[:6]:
        r = load(rid)
        out.append(
            {
                "run_id": rid,
                "name": r.meta.get("name", rid),
                "growth": points(r.equity / r.equity.iloc[0]),
                "stats": A.equity_stats(r.equity) | A.trade_stats(r.trades),
            }
        )
    return clean({"runs": out})


@router.get("/{run_id}")
def detail(run_id: str) -> dict:
    run = load(run_id)
    meta = {k: run.meta.get(k) for k in META_KEYS if k in run.meta}
    eq = run.equity
    trades = run.trades
    tr_stats = A.trade_stats(trades)
    monthly = A.monthly_returns(eq)
    months = [c for c in monthly.columns if c != "Year"]
    r = A.returns(eq)
    out = {
        "run_id": run_id,
        "meta": meta,
        "stats": A.equity_stats(eq, run.benchmark),
        "trade_stats": tr_stats,
        "equity": points(eq),
        "benchmark": points(benchmark_equity(run)),
        "drawdown": points(A.drawdown(eq)),
        "monthly": {
            "months": months,
            "rows": [
                {"year": int(y), "values": [row[m] for m in months], "total": row.get("Year")}
                for y, row in monthly.iterrows()
            ],
        },
        "rolling_sharpe": {str(w): points(A.rolling_sharpe(eq, w)) for w in (63, 126, 252)},
        "daily_hist": histogram(r * 100, 0.25),
        "drawdowns": table(A.drawdown_periods(eq)),
        "holdings": bundle.has_table(run_id, "holdings"),
        "trades": len(trades),
    }
    if len(trades):
        g = trades.sort_values("exit_time")
        by_year = g.groupby(g["exit_time"].dt.year)[["gross", "costs", "pnl"]].sum()
        by_year.index.name = "year"
        out["costs"] = {
            "gross": points(daily_cumsum(g["exit_time"], g["gross"])),
            "net": points(daily_cumsum(g["exit_time"], g["pnl"])),
            "by_year": table(by_year, index=True),
            "avg_per_trade": float(trades["costs"].mean()),
        }
        oos = meta.get("oos_start")
        if oos:
            split = A.split_stats(eq, trades, oos)
            out["split"] = table(split, index=True)
    return clean(out)


@router.get("/{run_id}/trades")
def trades(run_id: str) -> dict:
    run = load(run_id)
    if run.trades.empty:
        return {"trades": table(pd.DataFrame()), "dimensions": {}, "streaks": None}
    t = add_dimensions(run.trades)
    dims = [d for d in DIMENSIONS if d in t.columns]
    breakdowns = {}
    for d in dims:
        b = A.breakdown(t, d)
        b.index = b.index.astype(str)
        breakdowns[d] = table(b, index=True)
    s = A.streaks(t["pnl"])
    counts = s.groupby(["kind", "length"]).size().unstack(0, fill_value=0)
    worst = s[s.kind == "loss"].sort_values("pnl").head(1)
    cols = [c for c in TRADE_COLUMNS if c in t.columns] + ["result"]
    return clean(
        {
            "trades": table(t[cols]),
            "dimensions": breakdowns,
            "streaks": {
                "lengths": counts.index.astype(int).tolist(),
                "win": counts["win"].tolist() if "win" in counts else [],
                "loss": counts["loss"].tolist() if "loss" in counts else [],
                "worst_loss_streak_pnl": float(worst["pnl"].iloc[0]) if len(worst) else None,
            },
        }
    )


@router.get("/{run_id}/trades/{i}/bars")
def trade_chart(run_id: str, i: int) -> dict:
    run = load(run_id)
    if not 0 <= i < len(run.trades):
        raise HTTPException(404, "No such trade")
    tr = run.trades.iloc[i]
    bars = trade_bars(tr, run.meta.get("chart"))
    if bars.empty:
        return {"candles": [], "intraday": run.meta.get("chart") == "massive_minute"}
    candles = [
        {"t": t, "o": o, "h": h, "l": lo, "c": c}
        for t, o, h, lo, c in zip(
            seconds(bars.index), bars["open"], bars["high"], bars["low"], bars["close"],
            strict=True,
        )
    ]  # fmt: skip
    return clean(
        {
            "candles": candles,
            "intraday": run.meta.get("chart") == "massive_minute",
            "entry": {"t": seconds([tr["entry_time"]])[0], "px": tr["entry_px"]},
            "exit": {"t": seconds([tr["exit_time"]])[0], "px": tr["exit_px"]},
            "stop": tr.get("stop_px"),
            "win": bool(tr["pnl"] > 0),
            "exit_reason": tr.get("exit_reason", ""),
        }
    )


@router.get("/{run_id}/holdings")
def holdings(run_id: str, date: str | None = None) -> dict:
    run = load(run_id)
    if "holdings" not in run.tables:
        raise HTTPException(404, "This run has no holdings table")
    held = run.tables["holdings"].assign(date=lambda d: pd.to_datetime(d["date"]))
    picks = run.tables.get("picks")
    if picks is not None:
        picks = picks.assign(formation=pd.to_datetime(picks["formation"]))
    equity = run.equity
    cal = equity.index
    t = H.snap(cal, date or cal[-1])
    pos = H.positions_at(held, equity, t, picks)
    eq_t = float(equity.loc[t])
    out = {
        "name": run.meta.get("name", run_id),
        "strategy": run.meta.get("strategy", ""),
        "how_it_works": run.meta.get("how_it_works", ""),
        "caveats": run.meta.get("caveats", []),
        "calendar": [d.strftime("%Y-%m-%d") for d in cal],
        "date": t.strftime("%Y-%m-%d"),
        "equity_t": eq_t,
        "since_start": eq_t / float(equity.iloc[0]) - 1,
        "drawdown_t": eq_t / float(equity.loc[:t].max()) - 1,
        "cash_weight": 1.0 - float(pos["weight"].sum()) if len(pos) else 1.0,
        "positions": table(pos, index=True),
        "distinct": int(held["ticker"].nunique()),
        "rebalances": [],
        "ranking": None,
    }
    if picks is not None:
        trade_days = [
            cal[cal > f][0] for f in sorted(picks["formation"].unique()) if (cal > f).any()
        ]
        out["rebalances"] = [d.strftime("%Y-%m-%d") for d in trade_days]
        f = H.formation_for(picks, t)
        if f is not None:
            traded = cal[cal > f]
            ranked = picks[picks["formation"] == f].drop(columns="formation")
            out["ranking"] = {
                "formation": f.strftime("%Y-%m-%d"),
                "traded_on": traded[0].strftime("%Y-%m-%d") if len(traded) else None,
                "changes": H.rebalance_changes(picks, f),
                "table": table(ranked.sort_values("rank")),
            }
    return clean(out)


@router.get("/{run_id}/holdings/timeline")
def holdings_timeline(run_id: str) -> dict:
    run = load(run_id)
    if "holdings" not in run.tables:
        raise HTTPException(404, "This run has no holdings table")
    held = run.tables["holdings"].assign(date=lambda d: pd.to_datetime(d["date"]))
    periods = H.holding_periods(H.held_matrix(held, run.equity.index))
    return clean(
        {
            "equity": points(run.equity),
            "benchmark": points(benchmark_equity(run)),
            "periods": [
                {
                    "ticker": p.ticker,
                    "start": p.start.strftime("%Y-%m-%d"),
                    "end": p.end.strftime("%Y-%m-%d"),
                }
                for p in periods.itertuples()
            ],  # fmt: skip
        }
    )
