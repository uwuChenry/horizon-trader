import pandas as pd
import pytest

from horizon_trader.config import RiskSettings
from horizon_trader.portfolio import apply_risk_limits, combine_sleeves


def test_combine_scales_and_nets_across_sleeves():
    swing = pd.Series({"SPY": 1.0, "QQQ": -0.5})
    position = pd.Series({"SPY": -0.5, "TLT": 1.0})
    net = combine_sleeves({"swing": swing, "position": position}, {"swing": 0.4, "position": 0.6})
    assert net["SPY"] == pytest.approx(0.4 - 0.3)
    assert net["QQQ"] == pytest.approx(-0.2)
    assert net["TLT"] == pytest.approx(0.6)


def test_combine_drops_fully_offsetting_positions():
    net = combine_sleeves(
        {"a": pd.Series({"SPY": 0.5}), "b": pd.Series({"SPY": -0.5})}, {"a": 1.0, "b": 1.0}
    )
    assert "SPY" not in net


def test_risk_limits_cap_names_then_gross():
    w = pd.Series({"SPY": 0.9, "TLT": 0.5, "GLD": -0.4})
    out = apply_risk_limits(w, RiskSettings(max_weight=0.5, max_gross=1.0))
    assert out.abs().max() <= 0.5 + 1e-12
    assert out.abs().sum() == pytest.approx(1.0)
