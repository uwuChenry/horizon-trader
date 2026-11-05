"""JSON helpers: pandas objects -> plain lists/dicts the frontend can chart.

Times go out as "wall-clock seconds": New York local time for tz-aware stamps, read as if it were
UTC, so a chart that labels in UTC shows exchange time (9:30 is 9:30). Daily data is midnight.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

TZ = "America/New_York"
EPOCH = pd.Timestamp("1970-01-01")


def wall(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_convert(TZ).tz_localize(None)
    return idx


def seconds(index) -> list[int]:
    return ((wall(index) - EPOCH) // pd.Timedelta(seconds=1)).astype("int64").tolist()


def num(v: Any) -> Any:
    """A JSON-safe scalar: NaN/inf -> None, numpy -> Python."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    if isinstance(v, pd.Interval):
        return str(v)
    return v


def clean(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [clean(v) for v in obj]
    return num(obj)


def points(series: pd.Series | None) -> list[dict]:
    """[{t, v}] for a line chart, dropping missing values."""
    if series is None:
        return []
    s = series.dropna()
    s = s[np.isfinite(s.astype(float))]
    return [{"t": t, "v": float(v)} for t, v in zip(seconds(s.index), s.to_numpy(), strict=True)]


def table(df: pd.DataFrame, limit: int | None = None, index: bool = False) -> dict:
    """{columns, rows, total}: rows are lists in column order; NaN -> null, times -> ISO."""
    total = len(df)
    frame = df.head(limit) if limit else df
    if index:
        frame = frame.reset_index()
    frame = frame.copy()
    for c in frame.columns:
        col = frame[c]
        if isinstance(col.dtype, pd.CategoricalDtype | pd.IntervalDtype) or (
            col.dtype == object and col.map(lambda v: isinstance(v, pd.Interval)).any()
        ):
            frame[c] = col.astype(str).where(col.notna(), None)
    frame.columns = [str(c) for c in frame.columns]
    payload = json.loads(frame.to_json(orient="split", index=False, date_format="iso"))
    return {"columns": payload["columns"], "rows": payload["data"], "total": total}
