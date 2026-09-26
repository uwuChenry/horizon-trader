import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest import megacap as M


def test_top_n_keeps_one_share_class_per_company():
    caps = pd.DataFrame(
        {
            "ticker": ["AAPL", "GOOGL", "GOOG", "MSFT", "XYZ"],
            "market_cap": [3e12, 2e12, 1.9e12, 2.5e12, None],
            "cik": ["1", "2", "2", "3", "4"],
        }
    )
    assert list(M.top_n(caps, 3).index) == ["AAPL", "MSFT", "GOOGL"]  # GOOG dropped, XYZ no cap


def test_hold_period_lets_weights_drift_and_delisted_names_sit_in_cash():
    idx = pd.bdate_range("2024-01-02", periods=3)
    r = pd.DataFrame({"A": [0.10, 0.10, 0.0], "B": [0.0, np.nan, np.nan]}, index=idx)
    v = M.hold_period(r, pd.Series({"A": 1.0, "B": 1.0}))  # equal weight
    assert v.iloc[0] == pytest.approx(0.5 * 1.1 + 0.5)
    assert v.iloc[-1] == pytest.approx(0.5 * 1.21 + 0.5)  # B stopped trading: flat from then


def test_run_portfolio_chains_periods_from_the_day_after_formation():
    idx = pd.bdate_range("2024-01-29", "2024-02-06")
    r = pd.DataFrame({"A": 0.01, "B": -0.01}, index=idx)
    sched = {idx[2]: pd.Series({"A": 1.0}), idx[4]: pd.Series({"B": 1.0})}  # A, then B
    eq = M.run_portfolio(r, sched)
    assert eq.iloc[0] == 1.0 and eq.index[0] == idx[2]
    assert eq.loc[idx[4]] == pytest.approx(1.01**2)  # held A on idx[3], idx[4]
    assert eq.iloc[-1] == pytest.approx(1.01**2 * 0.99 ** (len(idx) - 5))


def test_month_ends_are_last_trading_days():
    idx = pd.to_datetime(["2024-01-30", "2024-01-31", "2024-02-01", "2024-02-29", "2024-03-01"])
    assert M.month_ends(pd.DatetimeIndex(idx)) == [idx[1], idx[3], idx[4]]
