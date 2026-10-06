import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest.research_stats import (
    bootstrap_diagnostics,
    choose_development,
    objective,
    risk_free,
)


def test_selection_enforces_drawdown_constraint_before_maximizing_growth():
    t = pd.DataFrame(
        {
            "cagr": [0.12, 0.20, 0.10, 0.11],
            "max_drawdown": [-0.3, -0.28, -0.15, -0.27],
            "calmar": [0.4, 0.7, 0.67, 0.41],
        },
        index=["qqq", "too_deep", "safe_slow", "safe_faster"],
    )
    choice = choose_development(t, list(t.index[1:]), "qqq")
    assert choice["selected"] == "safe_faster"
    assert not choice["fallback"]
    assert not objective(t.loc["safe_faster"], t.loc["qqq"])[0]


def test_calendar_risk_free_uses_previous_observation_over_weekend():
    idx = pd.to_datetime(["2026-01-02", "2026-01-05"])
    rate = pd.Series([0.04, 0.99], index=idx)
    assert risk_free(idx, rate).iloc[-1] == pytest.approx(0.04 * 3 / 360)


def test_paired_bootstrap_reproducible_and_identical_paths_have_no_growth_gap():
    rng = np.random.default_rng(17)
    ret = rng.normal(0.0004, 0.01, 200)
    frame = pd.DataFrame({"qqq": ret, "same": ret, "worse": ret - 0.001})
    a = bootstrap_diagnostics(frame, "qqq", ["same", "worse"], samples=100, block=20)
    b = bootstrap_diagnostics(frame, "qqq", ["same", "worse"], samples=100, block=20)
    pd.testing.assert_frame_equal(a, b)
    same = a.set_index("strategy").loc["same"]
    assert same.annual_log_growth_gap == pytest.approx(0)
    assert same.ci95_low == pytest.approx(0)
    assert same.ci95_high == pytest.approx(0)
    assert same.resampled_joint_objective_frequency == 0
    assert same.familywise_one_sided_p == 1
