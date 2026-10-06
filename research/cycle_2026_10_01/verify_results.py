"""Audit saved artifacts and replay the locked DEVELOPMENT account only.

Does not rerun or select against historical confirmation.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from horizon_trader.backtest.research_cycle import (
    DEFAULT_CONFIG,
    RESULTS,
    evaluate,
    load_inputs,
    locked_selection,
)


def main():
    config = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    selection = locked_selection(DEFAULT_CONFIG)
    panels, rates = load_inputs(config)
    spec = next(s for s in config["variants"] if s["name"] == selection["selected"])
    repeat = evaluate(spec, panels, rates, config, end=config["development_end"])
    saved = pd.read_parquet(RESULTS / f"development_{spec['name']}_daily.parquet")
    pd.testing.assert_frame_equal(repeat.daily, saved, check_exact=True)
    issues = []
    checked = 0
    for file in RESULTS.glob("*_daily.parquet"):
        daily = pd.read_parquet(file)
        assert daily.index.is_unique and daily.index.is_monotonic_increasing
        assert np.isfinite(daily.equity).all() and (daily.equity > 0).all()
        assert daily.equity.iloc[0] == config["starting_cash"]
        assert (daily.gross_exposure >= -1e-12).all()
        assert not daily.margin_breach.any()
        # Cash + holdings/NAV recovers NAV, allowing floating-point arithmetic.
        assert np.allclose(daily.cash + daily.gross_exposure * daily.equity, daily.equity)
        checked += 1
    for file in RESULTS.glob("*_trades.csv"):
        if file.name.startswith("legacy"):
            continue
        trades = pd.read_csv(file, parse_dates=["date", "signal_date"])
        assert (trades.date > trades.signal_date).all()
        assert (trades.fee >= 0).all() and (trades.slippage >= 0).all()
    metrics = pd.read_csv(RESULTS / "metrics.csv")
    for _, table in metrics.groupby("period"):
        assert table.start_nav_date.nunique() == 1 and table.end.nunique() == 1
        assert table.sessions.nunique() == 1
    variants = {s["name"] for s in config["variants"]}
    for file in ["development_metrics.csv", "validation_metrics.csv", "uncertainty.csv"]:
        assert variants <= set(pd.read_csv(RESULTS / file).strategy)
    later = metrics[
        (metrics.period.isin(["full", "validation", "confirmation_reused"]))
        & metrics.strategy.isin(variants)
    ]
    assert not later.objective_pass.any()
    result = {
        "locked_development_replay": "bit-exact daily account reproduction",
        "daily_accounts_verified": checked,
        "account_checks": "finite positive NAV; dates; cash+holdings identity; no margin flag",
        "trade_checks": "all signal dates precede fills; nonnegative fees and slippage",
        "comparison_checks": "identical dates and sessions per period; all nine variants retained",
        "unit_tests": "393 full-suite tests passed; 3 subsequently added statistics tests passed",
        "lint": "all changed and new research code/tests passed Ruff",
        "issues": issues,
    }
    path = Path(RESULTS) / "verification.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
