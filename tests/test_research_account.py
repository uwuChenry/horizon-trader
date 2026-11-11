"""Accounting identities and causal execution, independent of strategy signals."""

import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest.research_account import run_account
from horizon_trader.execution.costs import ZERO_COSTS, CostModel


def panel(values, symbols=("QQQ",), dates=None):
    if dates is None:
        dates = pd.bdate_range("2021-01-04", periods=len(values))
    return pd.DataFrame(values, index=dates, columns=list(symbols), dtype=float)


def test_signal_delay_and_no_future_changes_to_history():
    prices = panel([100, 110, 120, 130, 140])
    targets = panel([0, 1, np.nan, 0, np.nan])
    result = run_account(targets, prices, prices, prices, costs=ZERO_COSTS, delay=2)
    assert result.daily.equity.iloc[0] == 5_000
    assert result.daily.order_count.iloc[:3].sum() == 0
    assert result.trades.iloc[0]["date"] == prices.index[3]
    assert result.trades.iloc[0]["signal_date"] == prices.index[1]
    short = run_account(
        targets.iloc[:4],
        prices.iloc[:4],
        prices.iloc[:4],
        prices.iloc[:4],
        costs=ZERO_COSTS,
        delay=2,
    )
    pd.testing.assert_frame_equal(result.daily.iloc[:4], short.daily)
    with pytest.raises(ValueError, match="same-day"):
        run_account(targets, prices, prices, prices, delay=0)


def test_orders_use_previous_close_and_gap_resizes_are_flagged():
    targets = panel([1, np.nan, np.nan])
    flat = panel([100, 100, 100])
    gapped = panel([100, 200, 200])
    a = run_account(targets, flat, flat, flat, starting_cash=1_000, costs=ZERO_COSTS)
    b = run_account(targets, gapped, gapped, gapped, starting_cash=1_000, costs=ZERO_COSTS)
    assert a.trades.iloc[0].planned_quantity == b.trades.iloc[0].planned_quantity == 9
    assert b.trades.iloc[0].quantity == 5
    assert b.trades.iloc[0].reason == "opening_gap_resize"
    assert b.daily.cash_clipped.sum() == 1
    assert b.daily.cash.min() >= 0


def test_unlevered_account_is_self_financing_including_every_cost():
    prices = panel([[60, 80]] * 5, ("QQQ", "IEF"))
    targets = panel(
        [[0.5, 0.5], [np.nan, np.nan], [0, 0], [np.nan, np.nan], [0, 0]], ("QQQ", "IEF")
    )
    costs = CostModel(min_per_order=1, per_share=0, slippage_bps=100)
    result = run_account(targets, prices, prices, prices, costs=costs, starting_cash=1_000)
    assert (result.daily.cash >= 0).all()
    assert result.daily.borrow_cost.sum() == 0
    assert result.daily.gross_exposure.max() <= 1
    assert result.daily.equity.iloc[-1] == pytest.approx(1_000 - result.daily.costs.sum())
    assert result.daily.cash.iloc[-1] == result.daily.equity.iloc[-1]
    assert result.daily.costs.sum() == pytest.approx(
        result.trades.fee.sum() + result.trades.slippage.sum()
    )
    assert result.daily.notional_turnover.sum() == pytest.approx(result.trades.notional.sum())


def test_one_initial_order_matches_gross_dividend_reinvested_buy_and_hold():
    adjusted = panel([90, 90, 99, 99])
    raw = panel([100, 100, 100, 100])
    targets = panel([1, np.nan, np.nan, np.nan])
    result = run_account(
        targets,
        adjusted,
        adjusted,
        raw,
        starting_cash=1_000,
        costs=ZERO_COSTS,
        whole_shares=False,
        cash_buffer=0,
    )
    assert len(result.trades) == 1
    assert result.trades.quantity.iloc[0] == pytest.approx(10)
    assert result.trades.adjusted_quantity.iloc[0] == pytest.approx(1_000 / 90)
    assert result.daily.equity.tolist() == pytest.approx([1_000, 1_000, 1_100, 1_100])
    assert result.daily.equity.iloc[-1] == pytest.approx(1_000 * 99 / 90)


def test_whole_orders_and_fees_use_historical_raw_share_basis():
    adjusted = panel([20, 20, 20])
    raw = panel([100, 100, 100])
    targets = panel([0.95, np.nan, np.nan])
    costs = CostModel(per_share=1, min_per_order=0, slippage_bps=0)
    result = run_account(
        targets,
        adjusted,
        adjusted,
        raw,
        starting_cash=1_000,
        costs=costs,
        cash_buffer=0,
    )
    trade = result.trades.iloc[0]
    assert trade.quantity == 9
    assert trade.adjusted_quantity == 45
    assert trade.fee == 9
    assert trade.notional == 900
    assert result.daily.cash.iloc[-1] == 91
    assert result.daily.equity.iloc[-1] == 991


def test_weekend_financing_uses_actual_negative_cash_and_lagged_rate():
    dates = pd.to_datetime(["2021-01-07", "2021-01-08", "2021-01-11"])
    prices = panel([100, 100, 100], dates=dates)
    targets = panel([1.5, np.nan, np.nan], dates=dates)
    rates = pd.Series([0.036, 0.072, 0.108], index=dates)
    result = run_account(
        targets,
        prices,
        prices,
        prices,
        rates,
        starting_cash=1_000,
        costs=ZERO_COSTS,
        whole_shares=False,
        cash_buffer=0,
        borrow_spread=0.015,
    )
    assert result.daily.cash.iloc[1] == pytest.approx(-500)
    expected = 500 * (0.072 + 0.015) * 3 / 360
    assert result.daily.borrow_cost.iloc[-1] == pytest.approx(expected)
    assert result.daily.interest.iloc[-1] == pytest.approx(-expected)
    assert result.daily.equity.iloc[-1] == pytest.approx(1_000 - expected)


def test_missing_open_fails_closed_even_if_a_close_is_available():
    prices = panel([100, 100, 100])
    bad = panel([100, np.nan, 100])
    targets = panel([1, np.nan, np.nan])
    with pytest.raises(ValueError, match="adjusted_opens contains missing"):
        run_account(targets, bad, prices, prices)
    with pytest.raises(ValueError, match="raw_opens contains missing"):
        run_account(targets, prices, prices, bad)


def test_margin_breach_is_reported_without_inventing_liquidation_fill():
    prices = panel([100, 100, 60])
    targets = panel([1.5, np.nan, np.nan])
    result = run_account(
        targets,
        prices,
        prices,
        prices,
        costs=ZERO_COSTS,
        starting_cash=1_000,
        borrow_spread=0,
        whole_shares=False,
        cash_buffer=0,
    )
    assert result.daily.gross_exposure.iloc[-1] == pytest.approx(2.25)
    assert result.daily.margin_breach.tolist() == [False, False, True]
    assert len(result.trades) == 1


def test_return_to_unlevered_target_does_not_leave_rounding_debt():
    prices = panel([100, 100, 100, 100])
    targets = panel([1.5, 1, np.nan, np.nan])
    rates = pd.Series(0.05, index=prices.index)
    result = run_account(
        targets,
        prices,
        prices,
        prices,
        rates,
        costs=ZERO_COSTS,
        starting_cash=1_000,
        cash_buffer=0,
    )
    assert result.daily.cash.iloc[1] < 0
    assert (result.daily.cash.iloc[2:] >= 0).all()
    assert result.daily.gross_exposure.iloc[2:].max() <= 1


def test_only_complete_decisions_and_bounded_long_exposure_are_allowed():
    prices = panel([[100, 100]] * 3, ("QQQ", "IEF"))
    partial = panel([[1, np.nan], [np.nan, np.nan], [np.nan, np.nan]], ("QQQ", "IEF"))
    with pytest.raises(ValueError, match="complete finite long-only"):
        run_account(partial, prices, prices, prices)
    too_much = partial.fillna(0)
    too_much.iloc[0] = [1, 0.6]
    with pytest.raises(ValueError, match="must not exceed 1.5"):
        run_account(too_much, prices, prices, prices)


def test_cash_interest_is_zero_base_and_broker_scaled_sensitivity():
    prices = panel([100, 100, 100])
    targets = panel([0, np.nan, np.nan])
    rates = pd.Series(0.05, index=prices.index)
    zero = run_account(targets, prices, prices, prices, rates, starting_cash=50_000)
    paid = run_account(
        targets, prices, prices, prices, rates, starting_cash=50_000, cash_rate_mode="broker"
    )
    assert zero.daily.cash_income.sum() == 0
    assert paid.daily.cash_income.iloc[1] == pytest.approx(40_000 * 0.5 * 0.045 / 360)
