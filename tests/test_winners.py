import numpy as np
import pandas as pd

from horizon_trader.backtest import winners as W


def test_momentum_skips_the_last_month_and_has_no_lookahead():
    idx = pd.bdate_range("2022-01-03", periods=300)
    rng = np.random.default_rng(2)
    adj = pd.DataFrame(
        100 * np.cumprod(1 + rng.normal(0, 0.01, (300, 3)), axis=0), idx, list("ABC")
    )
    full = W.momentum(adj, 252, 21)
    t = 280
    expected = adj.iloc[t - 21] / adj.iloc[t - 252] - 1
    pd.testing.assert_series_equal(full.iloc[t], expected, check_names=False)
    cut = W.momentum(adj.iloc[: t + 1], 252, 21)  # cutting off the future doesn't change row t
    pd.testing.assert_series_equal(cut.iloc[t], full.iloc[t])


def test_schedules_pick_top_momentum_within_the_universe():
    idx = pd.bdate_range("2022-01-03", periods=60)
    adj = pd.DataFrame(
        {
            t: 100 * (1 + g) ** np.arange(60)
            for t, g in {"A": 0.01, "B": 0.005, "C": -0.01, "D": 0.02}.items()
        },
        index=idx,
    )
    data = {"adj": adj, "ends": [idx[40], idx[59]]}
    sched = W.schedules(data, 30, 5, 1, universe_at=lambda d: ["A", "B", "C"])  # D not in universe
    assert list(sched[idx[40]].index) == ["A"]
    assert all(len(s) == 1 for s in sched.values())


def test_momentum_is_unknown_across_a_reused_ticker_gap():
    # a ~$10 fund stops trading, then a different company lists under the same ticker at $150
    idx = pd.bdate_range("2024-01-01", periods=400)
    px = pd.Series(10.0, index=idx)
    px.iloc[200:270] = np.nan
    px.iloc[270:] = 150.0
    adj = pd.DataFrame({"X": px, "Y": 100.0})
    mom = W.momentum(adj, 252, 21)
    assert mom["X"].iloc[300:].isna().all()  # every window that spans the gap
    assert (mom["Y"].dropna() == 0).all() and mom["Y"].notna().iloc[300:].all()
    cut = W.momentum(adj.iloc[:301], 252, 21)  # still causal
    pd.testing.assert_series_equal(cut.iloc[300], mom.iloc[300])


def test_current_listing_starts_after_the_last_long_gap():
    idx = pd.bdate_range("2024-01-01", periods=300)
    px = pd.Series(10.0, index=idx)
    px.iloc[100:160] = np.nan
    px.iloc[160:] = 150.0
    s = W.current_listing(px)
    assert s.index[0] == idx[160] and (s == 150.0).all()
    assert len(W.current_listing(px.iloc[:100])) == 100  # no gap: the whole series
