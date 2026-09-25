import pandas as pd
import pytest
from conftest import trend

from horizon_trader.features.price import month_starts
from horizon_trader.sleeves.macd import MacdSleeve
from horizon_trader.sleeves.mean_reversion import MeanReversionSleeve
from horizon_trader.sleeves.momentum import MomentumRotationSleeve
from horizon_trader.sleeves.static import StaticSleeve
from horizon_trader.sleeves.trend import TrendFollowingSleeve
from horizon_trader.sleeves.vol_managed import VolManagedSleeve

SLEEVES = [
    MomentumRotationSleeve("mom", top_n=2),
    MeanReversionSleeve("mr", max_positions=2),
    StaticSleeve("static", {"A": 0.5, "B": 0.5}),
    TrendFollowingSleeve("tf"),
    VolManagedSleeve("vm", symbol="A"),
    MacdSleeve("macd", trend_window=200),
]


@pytest.mark.parametrize("sleeve", SLEEVES, ids=lambda s: s.name)
def test_no_lookahead(sleeve, random_prices):
    """Row t computed on the full history equals row t computed with the future cut off."""
    full = sleeve.weights_history(random_prices)
    for t in (260, 400, 599):
        truncated = sleeve.weights_history(random_prices.iloc[: t + 1])
        pd.testing.assert_series_equal(full.iloc[t], truncated.iloc[-1])


@pytest.mark.parametrize("sleeve", SLEEVES, ids=lambda s: s.name)
def test_live_weights_are_last_backtest_row(sleeve, random_prices):
    last = sleeve.weights_history(random_prices).iloc[-1]
    live = sleeve.target_weights(random_prices.index[-1], random_prices)
    pd.testing.assert_series_equal(live, last[last != 0])


@pytest.mark.parametrize("sleeve", SLEEVES, ids=lambda s: s.name)
def test_gross_weight_within_sleeve_capital(sleeve, random_prices):
    assert (sleeve.weights_history(random_prices).abs().sum(axis=1) <= 1.0 + 1e-12).all()


def _drifting(rates: dict[str, float], days: int = 400) -> pd.DataFrame:
    idx = pd.bdate_range("2020-01-01", periods=days)
    return pd.DataFrame({s: trend([r] * days) for s, r in rates.items()}, index=idx)


def test_momentum_holds_strongest_uptrends_and_leaves_rest_in_cash():
    prices = _drifting({"A": 0.001, "B": 0.0005, "C": -0.0005, "D": 0.0002})
    w = MomentumRotationSleeve("mom", top_n=3).weights_history(prices).iloc[-1]
    assert w.to_dict() == pytest.approx({"A": 1 / 3, "B": 1 / 3, "C": 0.0, "D": 1 / 3})

    falling = _drifting({"A": -0.001, "B": -0.0005})
    assert MomentumRotationSleeve("mom").weights_history(falling).iloc[-1].sum() == 0.0


def test_momentum_only_changes_on_month_starts(random_prices):
    w = MomentumRotationSleeve("mom", top_n=2).weights_history(random_prices)
    changed = w.diff().abs().sum(axis=1) > 0
    assert month_starts(random_prices.index)[changed].all()


def _dip_then_rally() -> pd.Series:
    rets = [0.003] * 260 + [-0.03] * 3 + [0.02] * 5
    return pd.DataFrame({"SPY": trend(rets)}, index=pd.bdate_range("2020-01-01", periods=268))


def test_mean_reversion_buys_the_dip_and_exits_on_the_rally():
    w = MeanReversionSleeve("mr", max_positions=3).weights_history(_dip_then_rally())["SPY"]
    assert w.iloc[:260].eq(0).all()  # steady uptrend: never oversold
    assert w.iloc[260:263].max() == pytest.approx(1 / 3)
    assert w.iloc[-1] == 0.0


def test_mean_reversion_time_stop():
    rets = [0.003] * 260 + [-0.03] + [-0.002] * 20  # oversold, then a slow bleed with no bounce
    prices = pd.DataFrame({"SPY": trend(rets)}, index=pd.bdate_range("2020-01-01", periods=281))
    w = MeanReversionSleeve("mr", max_hold=5).weights_history(prices)["SPY"]
    entry = int((w > 0).to_numpy().argmax())
    assert (w.iloc[entry : entry + 5] > 0).all()
    assert w.iloc[entry + 5] == 0.0


def test_trend_following_owns_every_uptrend_and_sizes_by_inverse_vol(random_prices):
    prices = random_prices.copy()
    prices["A"] = trend([0.002, -0.001] * 300)  # rising, calm
    prices["B"] = trend([0.006, -0.005] * 300)  # rising, daily std 0.0055 vs 0.0015
    prices["C"] = trend([-0.002, 0.001] * 300)  # falling
    w = TrendFollowingSleeve("tf", universe=["A", "B", "C"]).weights_history(prices).iloc[-1]
    assert w["C"] == 0.0
    assert w["A"] / w["B"] == pytest.approx(0.0055 / 0.0015, rel=0.02)
    assert w.sum() < 1.0  # C's risk budget stays in cash


def test_vol_managed_cuts_exposure_when_volatility_spikes():
    calm = [0.001, -0.0005] * 150
    wild = [0.03, -0.03] * 30
    idx = pd.bdate_range("2020-01-01", periods=len(calm) + len(wild) + 30)
    prices = pd.DataFrame({"SPY": trend(calm + wild + calm[:30])}, index=idx)
    w = VolManagedSleeve("vm", target_vol=0.15).weights_history(prices)["SPY"]
    assert w.loc[: idx[299]].max() == 1.0  # calm: capped at no leverage
    assert w.loc[idx[330] :].min() < 0.2  # after a month of ~48% vol, exposure is cut
