"""Per-symbol Parquet cache of daily bars under <data_dir>/bars, refreshed at most once a day."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from horizon_trader.config import data_dir

BarSource = Callable[[list[str]], dict[str, pd.DataFrame]]
FIELDS = ("open", "high", "low", "close", "volume")


def _path(symbol: str) -> Path:
    return data_dir() / "bars" / f"{symbol}.parquet"


def _is_stale(path: Path) -> bool:
    if not path.exists() or datetime.fromtimestamp(path.stat().st_mtime).date() < date.today():
        return True
    return not set(FIELDS) <= set(pd.read_parquet(path).columns)  # cached before OHLCV


def load_bars(
    symbols: list[str],
    start: str | None = None,
    refresh: bool = False,
    source: BarSource | None = None,
) -> dict[str, pd.DataFrame]:
    """Return {"open", "high", "low", "close", "volume"} panels (date x ticker), adjusted.

    Always caches full history (adjusted prices get rewritten after every dividend,
    so partial appends would mix adjustment bases); `start` only trims the result.
    """
    if source is None:
        from horizon_trader.datasources.yf_source import fetch_bars as source

    stale = [s for s in symbols if refresh or _is_stale(_path(s))]
    if stale:
        _path(stale[0]).parent.mkdir(parents=True, exist_ok=True)
        # A symbol the source fails to return keeps its old file (e.g. transient errors).
        for symbol, df in source(stale).items():
            df.to_parquet(_path(symbol))

    cached = {s: pd.read_parquet(_path(s)) for s in symbols if _path(s).exists()}
    frames = {s: f for s, f in cached.items() if set(FIELDS) <= set(f.columns)}
    panels = {
        field: pd.DataFrame({s: f[field] for s, f in frames.items()}).sort_index()
        for field in FIELDS
    }
    return {field: panel.loc[start:] for field, panel in panels.items()}
