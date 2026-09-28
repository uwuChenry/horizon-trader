import numpy as np
import pandas as pd
import pytest

from horizon_trader.pwb import audit, dual_class, short_vix, survivorship


def _days(n, start="2020-01-01"):
    return pd.bdate_range(start, periods=n)


# ---------------------------------------------------------------- audit


def test_parse_nav_and_positions_from_embedded_json():
    page = (
        r"x{\"date\":\"1990-01-02\",\"value\":100}y{\"date\":\"1990-01-31\",\"value\":101.5}"
        r"{\"date\":\"1990-01-31\",\"value\":101.5}"
        r"{\"ticker\":\"GTN\",\"position\":-15959}{\"ticker\":\"GTN-A\",\"position\":15959}"
        r"\"sharpeRatio\":1.97"
    )
    nav = audit.parse_nav(page)
    assert list(nav) == [100.0, 101.5]  # duplicate chart point dropped
    assert audit.parse_positions(page) == [("GTN", -15959.0), ("GTN-A", 15959.0)]
    assert audit.parse_page_metrics(page)["sharpeRatio"] == pytest.approx(1.97)


def test_a_cash_account_scores_a_huge_sharpe_at_rf_zero_but_none_in_excess():
    # A NAV that only earns the T-bill rate: this is how the site's 922 Sharpe happens.
    months = pd.date_range("2000-01-31", periods=120, freq="ME")
    rng = np.random.default_rng(0)
    rf = pd.Series(0.003 + rng.normal(0, 1e-5, len(months)), index=months)  # ~3.6%/yr
    nav = (1 + rf).cumprod() * 1e6
    market = pd.Series(rng.normal(0.008, 0.04, len(months)), index=months)
    s = audit.nav_stats(nav, rf, market)
    assert s["Sharpe rf=0"] > 100
    assert abs(s["Sharpe excess"]) < 2
    assert "mostly T-bill interest" in audit.flags([], s, None)


def test_readme_table_rows_parse():
    text = (
        "| [Good Carry, Bad Carry](https://paperswithbacktest.com/strategies/good-carry-bad-carry)"
        " | `1.74` | `10.6` | `4.6%` | `37` |"
    )
    df = audit.readme_table(text)
    assert df.loc[0, "slug"] == "good-carry-bad-carry"
    assert df.loc[0, "readme Sharpe"] == 1.74 and df.loc[0, "readme vol %"] == 4.6


# ---------------------------------------------------------------- dual class


def test_zscore_and_position_ignore_the_future():
    rng = np.random.default_rng(1)
    idx = _days(300)
    spread = pd.Series(np.cumsum(rng.normal(0, 0.01, 300)), index=idx)
    ok = pd.Series(True, index=idx)
    full = dual_class.pair_position(dual_class.zscore(spread), ok)
    cut = 200
    part = dual_class.pair_position(dual_class.zscore(spread.iloc[:cut]), ok.iloc[:cut])
    pd.testing.assert_series_equal(full.iloc[:cut], part)


def test_pair_position_opens_at_two_sigma_and_closes_at_zero_cross():
    z = pd.Series([0.5, 2.1, 1.5, 0.3, -0.1, -2.5, -1.0, 0.2], index=_days(8))
    ok = pd.Series(True, index=z.index)
    pos = dual_class.pair_position(z, ok)
    assert list(pos) == [0, -1, -1, -1, 0, 1, 1, 0]
    ok.iloc[2] = False  # pair stops being tradeable: flat at once
    assert dual_class.pair_position(z, ok).iloc[2] == 0


def _bounce_bars(n=400, seed=2):
    """Two identical share classes; B's close is A's plus bid/ask bounce, and B only trades
    every other day (a stale close otherwise)."""
    rng = np.random.default_rng(seed)
    idx = _days(n)
    a = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    b = a * (1 + rng.choice([-0.01, 0.01], n))
    vol_b = np.where(np.arange(n) % 2 == 0, 1000.0, 0.0)
    b_stale = pd.Series(np.where(vol_b > 0, b, np.nan), index=idx).ffill().bfill().to_numpy()
    close = pd.DataFrame({"A": a, "B": b_stale}, index=idx)
    return {
        "open": close.copy(),
        "high": close * 1.001,
        "low": close * 0.999,
        "close": close,
        "volume": pd.DataFrame({"A": 1e6, "B": vol_b}, index=idx),
    }


def test_same_close_fills_turn_bid_ask_bounce_into_fake_profit():
    bars = _bounce_bars()
    w = dual_class.weights(bars, [("A", "B")], liquid=False)
    same, _ = dual_class.simulate(bars, w, "same close")
    traded, _ = dual_class.simulate(bars, w, "traded days")
    assert same.iloc[-1] > 1.3  # pure noise looks like a great strategy
    assert traded.iloc[-1] < same.iloc[-1]


def test_traded_days_fill_waits_for_volume():
    bars = _bounce_bars(n=10)
    w = pd.DataFrame(0.0, index=bars["close"].index, columns=["A", "B"])
    w.iloc[2:, 1] = 0.5  # decided on day 2 (B trades on even days)
    _, d = dual_class.simulate(bars, w, "traded days")
    assert d["turnover"].iloc[3] == 0  # day 3: B has no volume, order waits
    assert d["turnover"].iloc[4] == pytest.approx(0.5)


def test_commission_minimum_is_charged_per_order():
    bars = _bounce_bars(n=5)
    w = pd.DataFrame(0.0, index=bars["close"].index, columns=["A", "B"])
    w.iloc[1:, 0] = 0.1
    _, d = dual_class.simulate(bars, w, "next close", capital=5_000)
    shares = 500 / bars["close"]["A"].iloc[2]  # $500 order, filled at day 2's close
    # a few shares: the $0.35 minimum plus clearing and exchange fees per share
    assert d["commission"].iloc[2] == pytest.approx((0.35 + shares * 0.0032) / 5_000)


# ---------------------------------------------------------------- short vix


def test_vrp_signal_ignores_the_future():
    rng = np.random.default_rng(3)
    idx = _days(200)
    spx = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 200))), index=idx)
    vix = pd.Series(15 + rng.normal(0, 2, 200), index=idx)
    full = short_vix.vrp_signal(vix, spx)
    part = short_vix.vrp_signal(vix.iloc[:120], spx.iloc[:120])
    pd.testing.assert_series_equal(full.iloc[:120], part)


def test_run_holds_yesterdays_signal_and_pays_switch_costs():
    idx = _days(4)
    r = pd.Series([0.0, 0.10, 0.10, 0.10], index=idx)
    sig = pd.Series([1.0, 1.0, 0.0, 0.0], index=idx)
    eq = short_vix.run(r, sig)
    c = short_vix.SWITCH_COST
    # enter on day 1 (signal of day 0), exit on day 3 (signal of day 2 is 0)
    assert eq.iloc[-1] == pytest.approx((1 + 0.10 - c) * (1 + 0.10) * (1 - c))


# ---------------------------------------------------------------- survivorship


def test_mdp_weights_are_inverse_vol_when_uncorrelated():
    cov = np.diag([0.1, 0.2]) ** 2
    w = survivorship.mdp_weights(cov)
    np.testing.assert_allclose(w, [2 / 3, 1 / 3], atol=1e-6)


def test_mdp_beats_every_long_only_mix_on_diversification_ratio():
    rng = np.random.default_rng(4)
    x = rng.normal(size=(500, 3)) @ np.array([[1, 0.6, 0.2], [0, 0.8, 0.3], [0, 0, 0.9]])
    cov = np.cov(x.T) * np.array([1, 2, 0.5])[:, None] * np.array([1, 2, 0.5])[None, :]
    best = survivorship.diversification_ratio(survivorship.mdp_weights(cov), cov)
    for w in rng.dirichlet(np.ones(3), 2000):
        assert survivorship.diversification_ratio(w, cov) <= best + 1e-9


def test_portfolios_use_only_past_prices():
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2019-01-01", "2021-12-31")
    close = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(idx), 25)), axis=0)),
        index=idx,
        columns=[f"S{i}" for i in range(25)],
    )
    full = survivorship.portfolios(close)
    part = survivorship.portfolios(close.loc[:"2021-06-30"])
    common = part.index
    pd.testing.assert_frame_equal(full.loc[common], part.loc[common])
