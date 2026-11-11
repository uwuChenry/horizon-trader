import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest import leverage as L


def _px(values, start="2024-01-01"):
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_accrual_charges_weekends_on_a_360_day_basis():
    idx = pd.DatetimeIndex(["2024-01-04", "2024-01-05", "2024-01-08"])  # Thu, Fri, Mon
    rate = pd.Series(0.036, index=pd.DatetimeIndex(["2024-01-01"]))
    acc = L.accrual(idx, rate)
    assert acc.iloc[0] == 0.0
    assert acc.iloc[1] == pytest.approx(0.036 / 360)
    assert acc.iloc[2] == pytest.approx(3 * 0.036 / 360)  # Fri -> Mon is three days


def test_constant_leverage_pays_interest_only_on_the_borrowed_part():
    ret = pd.Series([0.0, 0.01, -0.02], index=pd.bdate_range("2024-01-01", periods=3))
    borrow = pd.Series([0.0, 0.001, 0.001], index=ret.index)
    one = L.constant_leverage(ret, 1.0, borrow)
    np.testing.assert_allclose(one, (1 + ret).cumprod())  # 1x = buy and hold, no interest
    two = L.constant_leverage(ret, 2.0, borrow)
    assert two.iloc[-1] == pytest.approx((1 + 0.02 - 0.001) * (1 - 0.04 - 0.001))
    gone = L.constant_leverage(pd.Series([0.0, -0.3, 0.5], index=ret.index), 4.0, borrow * 0)
    assert (gone.iloc[1:] == 0).all()  # a -30% day at 4x wipes the account out for good


def test_margin_account_is_liquidated_below_maintenance():
    # 2x never rebalanced: $5k equity + $5k loan. A 40% drop leaves $6k position, $5k debt:
    # equity $1k < 25% of $6k, so IBKR sells back to 2x.
    px = _px([100.0, 100.0, 60.0, 60.0])
    no_interest = pd.Series(0.0, index=px.index)
    eq, info = L.margin_account(px, 2.0, no_interest, rebalance=False)
    assert info["liquidations"] == 1
    assert eq.iloc[2] < 1_000  # forced sale at 55 bps below the close, plus commissions
    assert eq.iloc[2] > 950


def test_margin_account_at_1x_matches_the_etf_less_costs():
    px = _px(100 * np.cumprod(1 + np.random.default_rng(0).normal(0, 0.01, 60)))
    eq, info = L.margin_account(px, 1.0, pd.Series(0.001, index=px.index), rebalance=True)
    assert info["interest $"] == 0.0 and info["liquidations"] == 0
    assert eq.iloc[-1] / 5_000 == pytest.approx(px.iloc[-1] / px.iloc[0], rel=0.002)


def test_mix_resets_weights_each_month_and_keeps_cash_flat():
    idx = pd.bdate_range("2024-01-29", periods=6)  # month changes on Feb 1 (4th row)
    r = pd.DataFrame({"X": [0, 0.10, 0.10, 0.10, 0.10, 0.10]}, index=idx, dtype=float)
    eq = L.mix(r, {"X": 0.5})
    assert eq.iloc[2] == pytest.approx(0.5 * 1.21 + 0.5)
    level = eq.iloc[2]  # Feb 1: reset to 50/50 of this level, then +10%
    assert eq.iloc[3] == pytest.approx(level * 0.5 * 1.1 + level * 0.5)
