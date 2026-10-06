"""Freeze local adjusted signals and separately retrieved nominal share prices.

Run after fetch_raw.py. Existing frozen inputs are never silently replaced.
The full available history is retained, with a common end date of 2026-09-30.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CYCLE = ROOT / "data" / "research_cycle_2026_10_01"
DEST = CYCLE / "inputs"
END = "2026-09-30"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    if (DEST / "manifest.json").exists():
        print(f"Frozen inputs already exist: {DEST}")
        return
    items = []
    for ticker in ("QQQ", "GLD", "IEF"):
        adjusted_path = ROOT / "data" / "bars" / f"{ticker}.parquet"
        raw_path = CYCLE / "raw" / f"{ticker}.parquet"
        adjusted = pd.read_parquet(adjusted_path).loc[:END]
        raw = pd.read_parquet(raw_path).loc[:END]
        # Yahoo OHLC and historical dividends are adjusted for subsequent splits.
        # Reverse only strictly subsequent splits; the ex-date uses post-split units.
        split = raw["Stock Splits"].replace(0.0, 1.0)
        subsequent_split = split.iloc[::-1].cumprod().iloc[::-1] / split
        frame = pd.DataFrame(
            {
                "adjusted_open": adjusted["open"],
                "adjusted_close": adjusted["close"],
                "raw_open": raw["Open"] * subsequent_split,
                "raw_close": raw["Close"] * subsequent_split,
                "dividend": raw["Dividends"] * subsequent_split,
                "split": raw["Stock Splits"],
            }
        ).reindex(adjusted.index)
        assert not frame.isna().any().any(), f"Missing inputs for {ticker}"
        assert frame.index.is_unique and frame.index.is_monotonic_increasing
        assert frame[["adjusted_open", "adjusted_close", "raw_open", "raw_close"]].gt(0).all().all()
        target = DEST / f"{ticker}.parquet"
        frame.to_parquet(target)
        items.append(
            {
                "ticker": ticker,
                "file": str(target.relative_to(ROOT)),
                "sha256": sha256(target),
                "rows": len(frame),
                "start": str(frame.index.min().date()),
                "end": str(frame.index.max().date()),
                "adjusted_source": str(adjusted_path.relative_to(ROOT)),
                "adjusted_source_sha256": sha256(adjusted_path),
                "raw_source": str(raw_path.relative_to(ROOT)),
                "raw_source_sha256": sha256(raw_path),
                "missing_values": 0,
                "nominal_price_method": "Yahoo Open times strictly subsequent split product",
            }
        )
    funding_source = ROOT / "data" / "reference" / "dff.parquet"
    funding = pd.read_parquet(funding_source).loc[:END]
    funding_target = DEST / "dff.parquet"
    funding.to_parquet(funding_target)
    manifest = {
        "frozen_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "common_end": END,
        "symbols": items,
        "funding": {
            "file": str(funding_target.relative_to(ROOT)),
            "sha256": sha256(funding_target),
            "source_sha256": sha256(funding_source),
            "rows": len(funding),
            "start": str(funding.index.min().date()),
            "end": str(funding.index.max().date()),
            "column": "ff",
            "units": "annual rate fraction",
            "tail_assumption": (
                "Forward-fill 2026-09-24 rate through 2026-09-30; do not interpolate"
            ),
        },
        "price_conventions": {
            "signals_returns": "Frozen existing split/dividend-adjusted Yahoo OHLC",
            "shares_fees": "Separately retrieved nominal contemporaneous share prices",
            "dividend_tax": (
                "Gross total return; withholding excluded consistently for benchmark and candidates"
            ),
        },
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
