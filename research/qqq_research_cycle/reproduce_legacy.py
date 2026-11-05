"""Reproduce the existing daily book from immutable local reads, without network refresh.

Run from the repository root:
    .venv/Scripts/python.exe research/cycle_2026_10_01/reproduce_legacy.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from horizon_trader.backtest.run import format_report, report, run_targets, target_histories
from horizon_trader.config import DEFAULT_CONFIG, load_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--data", type=Path, default=Path("data/bars"))
    parser.add_argument("--start", default="2008-01-01")
    parser.add_argument("--end", default="2026-09-30")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()
    settings = load_settings(args.config)
    symbols = sorted(set(settings.universe) | {"SPY", "QQQ"})
    manifest = []
    frames = {}
    for symbol in symbols:
        path = args.data / f"{symbol}.parquet"
        frame = pd.read_parquet(path).loc[: args.end]
        frames[symbol] = frame
        manifest.append(
            {
                "symbol": symbol,
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "rows": len(frame),
                "start": str(frame.index.min().date()),
                "end": str(frame.index.max().date()),
                "duplicate_dates": int(frame.index.duplicated().sum()),
                "missing_open_from_start": int(frame.loc[args.start :, "open"].isna().sum()),
                "missing_close_from_start": int(frame.loc[args.start :, "close"].isna().sum()),
                "nonpositive_close": int((frame["close"] <= 0).sum()),
            }
        )
    bars = {
        field: pd.DataFrame({symbol: f[field] for symbol, f in frames.items()}).sort_index()
        for field in ("open", "close")
    }
    histories = target_histories(settings, bars["close"])
    histories["QQQ buy&hold"] = pd.DataFrame({"QQQ": 1.0}, index=bars["close"].index)
    results = {
        name: run_targets(targets, bars, args.start, settings)
        for name, targets in histories.items()
    }
    table = report(results)
    equities = pd.DataFrame({name: result.equity for name, result in results.items()})
    cash_rows = []
    for name, result in results.items():
        fills = result.trades
        flow = -(fills["quantity"] * fills["price"] + fills["commission"])
        flows = pd.Series(flow.to_numpy(), index=pd.DatetimeIndex(fills["date"]))
        cash = (
            settings.account.starting_cash
            + flows.groupby(level=0).sum().reindex(result.equity.index, fill_value=0).cumsum()
        )
        borrowed_fraction = -cash.clip(upper=0) / result.equity
        cash_rows.append(
            {
                "name": name,
                "minimum_cash_dollars": cash.min(),
                "fraction_sessions_negative_cash": (cash < 0).mean(),
                "mean_borrowed_fraction_equity": borrowed_fraction.mean(),
                "max_borrowed_fraction_equity": borrowed_fraction.max(),
                "mean_net_exposure": ((result.equity - cash) / result.equity).mean(),
                "fills": len(fills),
            }
        )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "legacy_config.json").write_text(
        json.dumps(settings.model_dump(), indent=2) + "\n"
    )
    table.to_csv(args.output / "legacy_metrics.csv", index_label="strategy")
    equities.to_csv(args.output / "legacy_equity.csv", index_label="date")
    pd.DataFrame(cash_rows).to_csv(args.output / "legacy_cash_audit.csv", index=False)
    metadata = {
        "command": ".venv/Scripts/python.exe research/cycle_2026_10_01/reproduce_legacy.py",
        "requested_start": args.start,
        "requested_end": args.end,
        "actual_start": str(equities.index.min().date()),
        "actual_end": str(equities.index.max().date()),
        "config_path": str(args.config.resolve()),
        "config_sha256": hashlib.sha256(args.config.read_bytes()).hexdigest(),
        "config_snapshot": settings.model_dump(),
        "data": manifest,
        "notes": [
            "Read-only cached data; no load_bars refresh or external requests.",
            "Adjusted OHLC synthetic share accounting with dividend reinvestment approximation.",
            "First date is starting cash; all strategies first eligible at next open.",
            "Legacy engine charges no cash yield, financing or borrow costs.",
            "Source hashes cover complete files even though end date limits evaluation.",
        ],
    }
    (args.output / "legacy_manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(format_report(table))
    print(pd.DataFrame(cash_rows).to_string(index=False))
    print(f"Saved local audit under {args.output.resolve()}")


if __name__ == "__main__":
    main()
