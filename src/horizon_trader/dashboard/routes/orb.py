"""ORB day viewer: one day's Stocks in Play and each trade on a minute chart.

Reads the cached trade tables from `intraday.orb` and the Massive minute bars; nothing re-runs
the strategy, so the page shows exactly what the backtest simulated.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from horizon_trader.dashboard import orb_view as V
from horizon_trader.dashboard.serialize import clean, seconds, table
from horizon_trader.datasources import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

router = APIRouter(prefix="/api/orb")
MODE = "path"
TOP_N = [1, 2, 5, 10, 20]


@lru_cache(maxsize=4)
def trades(name: str) -> pd.DataFrame:
    if name not in V.stop_widths().values():
        raise HTTPException(404, f"No cached ORB table {name}")
    return V.load_trades(name)


@lru_cache(maxsize=8)
def day_bars(day: str, tickers: tuple[str, ...]) -> pd.DataFrame:
    """One filtered read of the day file for every ticker the page needs."""
    d = pd.Timestamp(day).date()
    path = massive.local_path("minute", d)
    if not path.exists():
        return pd.DataFrame(columns=["ticker", "ts", "open", "high", "low", "close", "volume"])
    start = F.session_open(d)
    window = [
        ("ticker", "in", list(tickers)),
        ("ts", ">=", start),
        ("ts", "<", start + orb.CLOSE_TIME),
    ]
    return pd.read_parquet(path, filters=window).reset_index(drop=True)


def bars_for(day: str, ticker: str, tickers: tuple[str, ...]) -> pd.DataFrame:
    b = day_bars(day, tickers)
    return b[b["ticker"] == ticker].reset_index(drop=True)


@router.get("/meta")
def meta() -> dict:
    widths = V.stop_widths()
    return {
        "widths": [{"label": k, "name": v} for k, v in widths.items()],
        "top_n": TOP_N,
        "rules": V.RULES_MD,
    }


@router.get("/days")
def days(width: str, top_n: int = 1) -> dict:
    t = trades(width)
    taken = t[(t["rank"] <= top_n) & t["triggered"]]
    r = taken["side"] * (taken[f"exit_px_{MODE}"] - taken["entry_px"]) / taken["stop_dist"]
    by_day = r.groupby(taken["date"]).sum()
    return clean(
        {
            "dates": [d.strftime("%Y-%m-%d") for d in sorted(t["date"].unique())],
            "traded": [{"date": d.strftime("%Y-%m-%d"), "R": v} for d, v in by_day.items()],
        }
    )


@router.get("/day")
def day(width: str, date: str, top_n: int = 1, slip: float = Query(0.0, ge=0, le=0.5)) -> dict:
    t = trades(width)
    when = pd.Timestamp(date)
    table_ = V.day_table(t, when, top_n, MODE)
    if table_.empty:
        return {"date": date, "candidates": None, "summary": None}
    show = table_.head(max(10, top_n))
    tickers = tuple(sorted(show["ticker"]))
    mine = table_[table_["taken"]]
    sized = []
    for _, row in mine[mine["triggered"]].iterrows():
        p = V.trade_path(row, bars_for(date, row["ticker"], tickers), MODE)
        sized.append(V.size_trade(row, p, top_n, slippage=slip))
    cols = ["rank", "ticker", "taken", "relvol", "direction", "level", "stop_px", "triggered",
            "entry_time", "exit_reason", f"exit_px_{MODE}", "R"]  # fmt: skip
    view = show[cols].rename(columns={f"exit_px_{MODE}": "exit_px"})
    return clean(
        {
            "date": date,
            "candidates": table(view),
            "summary": {
                "candidates": int(len(table_)),
                "top": int(len(mine)),
                "broke_out": int(mine["triggered"].sum()),
                "day_R": float(mine["R"].fillna(0).sum()),
                "day_net": float(sum(s["net $"] for s in sized)),
                "capital": V.CAPITAL,
            },
        }
    )


@router.get("/chart")
def chart(
    width: str,
    date: str,
    ticker: str,
    top_n: int = 1,
    slip: float = Query(0.0, ge=0, le=0.5),
) -> dict:
    t = trades(width)
    table_ = V.day_table(t, pd.Timestamp(date), top_n, MODE)
    if ticker not in set(table_["ticker"]):
        raise HTTPException(404, f"{ticker} was not a candidate on {date}")
    tickers = tuple(sorted(table_.head(max(10, top_n))["ticker"]))
    if ticker not in tickers:
        tickers = tuple(sorted({*tickers, ticker}))
    row = table_.set_index("ticker").loc[ticker].copy()
    row["ticker"] = ticker
    b = bars_for(date, ticker, tickers)
    if b.empty:
        return {"candles": [], "path": None}
    path = V.trade_path(row, b, MODE)
    out = {
        "ticker": ticker,
        "rank": int(row["rank"]),
        "relvol": float(row["relvol"]),
        "side": int(row["side"]),
        "taken": bool(row["taken"]),
        "candles": [
            {"t": s, "o": o, "h": h, "l": lo, "c": c, "v": v}
            for s, o, h, lo, c, v in zip(
                seconds(b["ts"]),
                b["open"],
                b["high"],
                b["low"],
                b["close"],
                b["volume"],
                strict=True,
            )
        ],  # fmt: skip
        "or_end": seconds(
            [F.session_open(pd.Timestamp(date).date()) + pd.Timedelta(minutes=V.MINUTES)]
        )[0],  # fmt: skip
        "path": {
            k: (seconds([v])[0] if isinstance(v, pd.Timestamp) else v) for k, v in path.items()
        },  # fmt: skip
        "sizing": None,
    }
    if path["triggered"]:
        s = V.size_trade(row, path, top_n, slippage=slip)
        r_mult = row["side"] * (path["exit_px"] - path["entry_px"]) / row["stop_dist"]
        out["sizing"] = s | {"R": r_mult, "capital": V.CAPITAL}
    return clean(out)
