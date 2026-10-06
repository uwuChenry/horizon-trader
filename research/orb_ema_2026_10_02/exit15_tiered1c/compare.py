"""Reprice the saved 5-minute exits and audit the 15-minute-exit follow-up."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.config import data_dir
from horizon_trader.datasources import massive
from horizon_trader.intraday import orb_ema as E


def main():
    output = Path(__file__).parent
    manifest = json.loads((output / "manifest.json").read_text())
    original = json.loads((output.parent / "manifest.json").read_text())
    assert (manifest["first"], manifest["last"], manifest["sessions"], manifest["skipped"]) == (
        original["first"],
        original["last"],
        original["sessions"],
        0,
    )
    for filename in ("orb5_stop1_trades.parquet", "splits.parquet"):
        old_hash = next(v for k, v in original["sha256"].items() if Path(k).name == filename)
        new_hash = next(v for k, v in manifest["sha256"].items() if Path(k).name == filename)
        assert old_hash == new_hash, f"Source changed: {filename}"
    old_path = data_dir() / "orb_ema_2026_10_02/trades_5m.parquet"
    new_path = Path(manifest["trades_path"])
    old, new = pd.read_parquet(old_path), pd.read_parquet(new_path)
    keys = ["date", "ticker", "variant", "stop_atr"]
    for frame in (old, new):
        assert not frame.duplicated(keys).any()
        assert (frame.exit_time >= frame.entry_time).all()
        assert np.isfinite(frame[["entry_px", "exit_px_cons", "gross_R"]]).all().all()
    paired = old.merge(new, on=keys, suffixes=("_5m", "_15m"), validate="one_to_one")
    assert len(paired) == len(old) == len(new)
    assert (paired.entry_time_5m == paired.entry_time_15m).all()
    for col in ("entry_px", "side", "stop_dist"):
        np.testing.assert_allclose(paired[f"{col}_5m"], paired[f"{col}_15m"], atol=1e-10)
    base = paired[paired.variant == "orb"]
    np.testing.assert_allclose(base.exit_px_cons_5m, base.exit_px_cons_15m, atol=1e-10)
    assert (base.exit_time_5m == base.exit_time_15m).all()
    ema = new[new.exit_reason == "ema"]
    delayed = ema[ema.exit_time.dt.minute % 15 != 0].drop_duplicates(
        ["date", "ticker", "side", "exit_time"]
    )
    # A missing minute delays the fill, not the signal. Reconstruct each such
    # event and prove it used the first observed open after a completed candle.
    artifacts = data_dir() / "orb_ema_2026_10_02"
    cached = pd.read_parquet(
        artifacts / f"inputs_{manifest['input_key']}.parquet",
        filters=[("ticker", "in", delayed.ticker.unique().tolist())],
    )
    groups = dict(tuple(cached.groupby(["date", "ticker"], sort=False)))
    splits = pd.read_parquet(data_dir() / "massive/reference/splits.parquet")
    all_days = pd.DatetimeIndex(massive.local_days())
    for row in delayed.itertuples():
        pos = all_days.get_loc(row.date)
        today = groups[(row.date, row.ticker)].sort_values("ts")
        prior = [
            groups[(d, row.ticker)]
            for d in all_days[max(0, pos - 5) : pos]
            if (d, row.ticker) in groups
        ]
        history = E.adjust_history(pd.concat(prior), row.date, splits[splits.ticker == row.ticker])
        signals = E.ema_signals(history, today, E.Rules(candle_minutes=15))
        last = signals[signals.signal_time <= row.exit_time].iloc[-1]
        assert row.side * (last.close - last.ema) < 0
        first = today[today.ts >= last.signal_time].iloc[0]
        assert first.ts == row.exit_time
        assert np.isclose(first.open, row.exit_px_cons)

    calendar = pd.DatetimeIndex(massive.local_days())
    calendar = calendar[(calendar >= manifest["first"]) & (calendar <= manifest["last"])]
    assert len(calendar) == manifest["sessions"]
    costs = [("gross", "none", 0.0), ("tiered_1c", "tiered", 0.01)]
    comparison = pd.concat(
        [
            E.evaluate(old, calendar, costs).assign(exit_minutes=5),
            E.evaluate(new, calendar, costs).assign(exit_minutes=15),
        ],
        ignore_index=True,
    )
    assert len(comparison) == 4 * 5 * 2 * 3 * 2
    assert np.isfinite(comparison[["CAGR", "Sharpe", "max DD", "final"]]).all().all()
    actual = pd.read_csv(output / "metrics.csv")
    pd.testing.assert_frame_equal(
        comparison[comparison.exit_minutes == 15]
        .drop(columns="exit_minutes")
        .reset_index(drop=True),
        actual,
        check_exact=False,
        rtol=1e-10,
        atol=1e-10,
    )
    comparison.to_csv(output / "comparison.csv", index=False)
    curves, details = {}, []
    for minutes, frame in ((5, old), (15, new)):
        for variant, group in frame[frame.stop_atr == 1].groupby("variant"):
            curve, fills = E.portfolio(group, calendar, "tiered", 0.01)
            curves[f"{variant}_{minutes}m"] = curve
            details.append(
                {
                    "variant": variant,
                    "exit_minutes": minutes,
                    "round_trips": len(group),
                    "sized_trades": len(fills),
                    "mean_minutes": (group.exit_time - group.entry_time).dt.total_seconds().mean()
                    / 60,
                    "mean_gross_R": group.gross_R.mean(),
                    "stop_fraction": (group.exit_reason == "stop").mean(),
                    "ema_exit_fraction": (group.exit_reason == "ema").mean(),
                }
            )
    pd.DataFrame(curves).to_csv(output / "equity_1atr.csv", index_label="date")
    pd.DataFrame(details).to_csv(output / "trade_details_1atr.csv", index=False)
    dependencies = [
        Path(E.__file__),
        Path(E.orb.__file__),
        Path("src/horizon_trader/execution/costs.py"),
        Path("src/horizon_trader/backtest/metrics.py"),
        Path("tests/test_orb_ema.py"),
        Path(__file__),
        old_path,
        new_path,
    ]
    verification = {
        "sessions": len(calendar),
        "comparison_rows": len(comparison),
        "matched_entries_all_stops": len(paired),
        "unchanged_baseline_trades_all_stops": len(base),
        "entry_price_or_time_disagreements": 0,
        "audited_delayed_ema_exit_events": len(delayed),
        "entry_rules": "5-minute; all entry times/prices match the original run",
        "exit_rules": "15-minute EMA(12); completed candles, next available minute open",
        "tests": "48 passed: test_orb_ema.py, test_orb.py, test_ema_vwap.py",
        "sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies},
    }
    (output / "verification.json").write_text(json.dumps(verification, indent=2), encoding="utf-8")
    print(
        comparison[(comparison.stop_atr == 1) & (comparison.period == "all")][
            ["variant", "exit_minutes", "cost_case", "CAGR", "Sharpe", "max DD", "trades"]
        ]
        .round(4)
        .to_string(index=False)
    )
    print(f"Verified {len(paired):,} unchanged entries across every stop width.")


if __name__ == "__main__":
    main()
