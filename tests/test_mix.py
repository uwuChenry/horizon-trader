import pandas as pd
import pytest

from horizon_trader.backtest import mix


def test_blend_sums_separate_sub_accounts_on_a_common_calendar():
    idx = pd.bdate_range("2024-01-01", periods=4)
    a = pd.Series([2500.0, 2750.0, 2750.0, 3000.0], index=idx)  # +20% in total
    b = pd.Series([2500.0, 2500.0, 2250.0], index=idx[[0, 1, 3]])  # misses a day: carried flat
    total = mix.blend({"a": a, "b": b})
    assert list(total) == [5000.0, 5250.0, 5250.0, 5250.0]
    assert total.iloc[-1] / total.iloc[0] - 1 == pytest.approx(0.05)  # (20% - 10%) / 2


def test_period_stats_split_keeps_the_base_before_the_split():
    idx = pd.bdate_range("2023-12-01", "2024-01-31")
    eq = pd.Series(range(100, 100 + len(idx)), index=idx, dtype=float)
    s = mix.period_stats(eq)
    assert {"all CAGR", "2021-23 Sharpe", "2024-26 max DD"} <= set(s)
    assert s["2024-26 max DD"] == 0.0  # monotonic curve


def test_overlay_adds_daily_returns_on_the_same_capital():
    idx = pd.bdate_range("2024-01-01", periods=3)
    r = pd.DataFrame({"daily book": [0.01, -0.01, 0.02], "ORB": [0.005, 0.0, -0.01]}, index=idx)
    eq = mix.overlay(r, ["daily book", "ORB"], 1000.0)
    assert eq.iloc[0] == 1000.0 and eq.iloc[1] == pytest.approx(1015.0)
    assert eq.iloc[-1] == pytest.approx(1000 * 1.015 * 0.99 * 1.01)
