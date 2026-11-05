"""Freeze Yahoo raw/action inputs for the October 2026 research cycle only.

Run: .venv/Scripts/python.exe research/cycle_2026_10_01/fetch_raw.py
Never overwrites the repository's normal data/bars cache. Yahoo OHLC is split
adjusted even with auto_adjust=False; actions allow reconstruction of contemporaneous
share prices. Dividends and adjustments are preserved for audit, not silently used
to revise the already frozen strategy input history.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "data" / "research_cycle_2026_10_01" / "raw"


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(DEST / "yfinance-cache"))
    summaries = []
    for ticker in ("QQQ", "GLD", "IEF"):
        target = DEST / f"{ticker}.parquet"
        if target.exists():
            frame = pd.read_parquet(target)
        else:
            frame = yf.download(
                ticker,
                period="max",
                auto_adjust=False,
                actions=True,
                threads=False,
                progress=False,
            )
            if frame.empty:
                raise RuntimeError(f"Yahoo returned no data for {ticker}")
            if isinstance(frame.columns, pd.MultiIndex):
                frame = frame.xs(ticker, axis=1, level=1)
            frame.to_parquet(target)
        cached = pd.read_parquet(ROOT / "data" / "bars" / f"{ticker}.parquet")
        comparable = pd.concat(
            [frame["Adj Close"].rename("fetched"), cached["close"].rename("cached")], axis=1
        ).dropna()
        relative = comparable.fetched / comparable.cached - 1
        splits = frame.loc[frame["Stock Splits"].ne(0), "Stock Splits"]
        report = {
            "ticker": ticker,
            "file": str(target.relative_to(ROOT)),
            "retrieved_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "rows": len(frame),
            "start": str(frame.index.min().date()),
            "end": str(frame.index.max().date()),
            "columns": frame.columns.tolist(),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "adjusted_cache_overlap_rows": len(comparable),
            "max_absolute_adjustment_difference": float(relative.abs().max()),
            "median_adjustment_difference": float(relative.median()),
            "splits": {str(k.date()): float(v) for k, v in splits.items()},
            "dividend_events": int(frame["Dividends"].ne(0).sum()),
        }
        summaries.append(report)
        print(json.dumps(report), flush=True)
    (DEST / "manifest.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
