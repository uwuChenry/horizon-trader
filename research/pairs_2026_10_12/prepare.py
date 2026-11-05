"""Freeze daily bars/actions for the predeclared competitor-pairs experiment."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/pairs_2026_10_12/raw"
SYMBOLS = ["KO", "PEP", "HD", "LOW", "MCD", "YUM", "V", "MA", "XOM", "CVX", "SPY"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(OUT.parent / "yf-cache"))
    rows = []
    for symbol in SYMBOLS:
        path = OUT / f"{symbol}.parquet"
        if not path.exists():
            # Full action history is needed to undo Yahoo's retrospective split basis.
            frame = yf.download(
                symbol,
                period="max",
                auto_adjust=False,
                actions=True,
                threads=False,
                progress=False,
                timeout=25,
            )
            if isinstance(frame.columns, pd.MultiIndex):
                frame = frame.xs(symbol, axis=1, level=1)
            required = {"Open", "Close", "Adj Close", "Dividends", "Stock Splits", "Volume"}
            if frame.empty or not required.issubset(frame.columns):
                raise RuntimeError(f"Missing bars/actions for {symbol}")
            frame.to_parquet(path)
        frame = pd.read_parquet(path)
        rows.append(
            {
                "symbol": symbol,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "first": str(frame.index.min()),
                "last": str(frame.index.max()),
                "rows": len(frame),
            }
        )
        print(f"Frozen {symbol}: {len(frame)} rows, last {frame.index.max()}", flush=True)
    info = {
        "frozen_utc": datetime.now(UTC).isoformat(),
        "source": "Yahoo via yfinance",
        "files": rows,
    }
    (OUT / "manifest.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
