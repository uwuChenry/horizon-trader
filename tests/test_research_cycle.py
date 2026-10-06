import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest.research_stats import drawdown_days, slice_period
from horizon_trader.sleeves.research_cycle import ResearchCycleSleeve


def prices():
    rng = np.random.default_rng(12)
    idx = pd.bdate_range("2000-01-03", periods=500)
    return pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, (500, 3)), axis=0)),
        index=idx,
        columns=["QQQ", "GLD", "IEF"],
    )


@pytest.mark.parametrize(
    "family,params",
    [
        ("trend", {"trend": 100}),
        ("voltrend", {"trend": 200, "vol_window": 63, "target_vol": 0.2, "cap": 1.5}),
        ("rotation", {"trend": 200, "lookback": 252, "skip": 21}),
    ],
)
def test_future_prices_cannot_change_prior_signals(family, params):
    px = prices()
    sleeve = ResearchCycleSleeve("test", family, **params)
    before = sleeve.decision_history(px.iloc[:400], str(px.index[320].date()))
    changed = px.copy()
    changed.iloc[400:] *= np.arange(1, 101)[:, None]
    after = sleeve.decision_history(changed, str(px.index[320].date()))
    pd.testing.assert_frame_equal(before, after.loc[before.index])


def test_buy_hold_has_one_decision_and_monthly_rule_is_close_causal():
    px = prices()
    start = str(px.index[320].date())
    buy = ResearchCycleSleeve("buy", "buy_hold").decision_history(px, start)
    assert buy.dropna().shape[0] == 1
    assert buy.dropna()["QQQ"].iloc[0] == 1
    trend = ResearchCycleSleeve("trend", "trend", trend=100).decision_history(px, start)
    dates = trend.dropna().index[1:]
    periods = px.index.to_period("M")
    for day in dates:
        i = px.index.get_loc(day)
        assert periods[i] != periods[i - 1]


def test_rotation_stays_in_cash_if_all_trends_negative():
    px = prices()
    px.iloc[:, :] = np.linspace(1000, 1, len(px))[:, None]
    sleeve = ResearchCycleSleeve("rotate", "rotation", trend=200, lookback=252, skip=21)
    assert sleeve.daily_signal(px).sum().sum() == 0


def test_period_boundary_retains_first_return_and_drawdown_duration():
    idx = pd.to_datetime(["2020-12-31", "2021-01-04", "2021-01-05", "2021-01-06"])
    eq = pd.DataFrame({"equity": [100, 90, 99, 101]}, index=idx)
    window = slice_period(eq, "2021-01-01", "2021-12-31")
    assert window.equity.pct_change().iloc[1] == pytest.approx(-0.1)
    assert drawdown_days(window.equity) == 6
    assert drawdown_days(pd.Series([100, 101, 102, 103], index=idx)) == 0
