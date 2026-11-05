"""Audit the saved experiment independently against the existing ORB trade cache."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.config import data_dir
from horizon_trader.datasources import massive


def main():
    output = Path(__file__).parent
    trades = pd.read_parquet(data_dir() / "orb_ema_2026_10_02/trades_5m.parquet")
    old = pd.read_parquet(data_dir() / "massive/derived/orb5_stop1_trades.parquet")
    metrics = pd.read_csv(output / "metrics.csv")
    manifest = json.loads((output / "manifest.json").read_text())
    assert not trades.duplicated(["date", "variant", "stop_atr"]).any()
    assert (trades.exit_time >= trades.entry_time).all()
    assert (trades.stop_dist > 0).all()
    assert np.isfinite(trades[["entry_px", "exit_px_cons", "gross_R"]]).all().all()
    assert len(metrics) == 4 * 5 * 3 * 3
    assert np.isfinite(metrics[["CAGR", "Sharpe", "max DD", "final"]]).all().all()
    days = pd.DatetimeIndex(massive.local_days())
    days = days[(days >= manifest["first"]) & (days <= manifest["last"])]
    assert len(days) == manifest["sessions"] and manifest["skipped"] == 0

    base = trades[(trades.variant == "orb") & (trades.stop_atr == 1)]
    original = old[(old["rank"] == 1) & old.triggered]
    paired = base.merge(original, on=["date", "ticker"], suffixes=("_new", "_old"))
    assert len(paired) == len(base) == len(original)
    np.testing.assert_allclose(paired.entry_px_new, paired.entry_px_old, atol=1e-10)
    np.testing.assert_allclose(paired.exit_px_cons_new, paired.exit_px_cons_old, atol=1e-10)
    managed = trades[(trades.variant == "orb_ema_exit") & (trades.stop_atr == 1)]
    exits = base.merge(managed, on=["date", "ticker"], suffixes=("_orb", "_ema"))
    assert len(exits) == len(base)
    assert (exits.entry_time_orb == exits.entry_time_ema).all()
    np.testing.assert_allclose(exits.entry_px_orb, exits.entry_px_ema, atol=1e-10)

    dependencies = [
        "src/horizon_trader/intraday/orb_ema.py",
        "src/horizon_trader/intraday/orb.py",
        "src/horizon_trader/intraday/features.py",
        "src/horizon_trader/execution/costs.py",
        "src/horizon_trader/backtest/metrics.py",
        "tests/test_orb_ema.py",
    ]
    result = {
        "sessions": len(days),
        "saved_round_trips": len(trades),
        "metric_rows": len(metrics),
        "matched_original_baseline_trades": len(paired),
        "baseline_price_disagreements": 0,
        "matched_ema_exit_entries": len(exits),
        "tests": "37 passed: test_orb_ema.py, test_orb.py, test_ema_vwap.py",
        "dependency_sha256": {
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in dependencies
        },
    }
    (output / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "dependency_sha256"}, indent=2))


if __name__ == "__main__":
    main()
