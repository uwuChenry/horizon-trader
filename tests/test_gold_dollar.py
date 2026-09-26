import numpy as np
import pandas as pd
import pytest

from horizon_trader.macro import gold_dollar as G


def prices(n: int = 400, seed: int = 0) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n)
    rd = rng.normal(0, 0.005, n)
    rg = -0.8 * rd + rng.normal(0, 0.009, n)  # inverse, like gold vs the dollar
    return (
        pd.Series(100 * np.cumprod(1 + rg), idx, name="GLD"),
        pd.Series(25 * np.cumprod(1 + rd), idx, name="UUP"),
    )


def test_signals_ignore_the_future():
    """Cutting off or changing later prices never changes an earlier signal row."""
    gold, dollar = prices(n=700)
    full = G.signals(gold, dollar)
    cut = gold.index[600]
    short = G.signals(gold[:cut], dollar[:cut])
    pd.testing.assert_frame_equal(full[:cut], short)
    g2, d2 = prices(n=700, seed=9)
    mixed = G.signals(
        pd.concat([gold[:cut], g2[g2.index > cut]]), pd.concat([dollar[:cut], d2[d2.index > cut]])
    )
    pd.testing.assert_frame_equal(mixed[:cut], short)
    assert short.iloc[-1].notna().all()


def test_rolling_beta_recovers_slope_and_is_ex_ante():
    gold, dollar = prices(n=600)
    beta = G.rolling_beta(gold.pct_change(), dollar.pct_change(), 250)
    assert beta.iloc[-1] == pytest.approx(-0.8, abs=0.3)
    rg, rd = gold.pct_change(), dollar.pct_change()
    exact = rg.iloc[-251:-1].cov(rd.iloc[-251:-1]) / rd.iloc[-251:-1].var()
    assert beta.iloc[-1] == pytest.approx(exact)  # window ends at t-1


def test_residual_gap_sign():
    """Gold jumping while the dollar is flat = gold ran ahead -> negative signal (sell)."""
    gold, dollar = prices(n=700)
    gold = gold.copy()
    gold.iloc[-1] *= 1.05
    assert G.residual_gap(gold, dollar, 5).iloc[-1] < 0


def test_forward_return_starts_at_next_open():
    opens = pd.Series([10.0, 11.0, 12.0, 15.0, 16.0])
    fwd = G.forward_return(opens, 2)
    assert fwd.iloc[0] == pytest.approx(15.0 / 11.0 - 1)  # open t+1 -> open t+3
    assert fwd.iloc[-3:].isna().all()


def test_newey_west_matches_plain_t_without_lags():
    x = pd.Series(np.random.default_rng(1).normal(0.1, 1, 500))
    plain = x.mean() / (x.std(ddof=0) / np.sqrt(len(x)))
    assert G.newey_west_t(x, 0) == pytest.approx(plain)
    overlapping = x.rolling(20).sum().dropna()  # heavily autocorrelated
    assert abs(G.newey_west_t(overlapping, 20)) < abs(G.newey_west_t(overlapping, 0))


def test_random_control_keeps_time_in_market():
    idx = pd.bdate_range("2020-01-01", periods=500)
    sig = pd.Series(np.sin(np.arange(500) / 7), idx)
    t = G.long_flat_targets(sig, "W")
    r = pd.concat([G.random_targets(t, s)[G.GOLD] for s in range(30)])
    assert r.mean() == pytest.approx(t[G.GOLD].mean(), abs=0.08)
    assert set(r.dropna().unique()) <= {0.0, 1.0}
