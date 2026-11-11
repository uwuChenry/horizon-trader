import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import orb_ideas as I

A = np.array


def _bars():
    # long filled at 10.0 in minute 0, 1R = 1.0; the price runs to 12.2, then falls to 9.5
    o = A([10.0, 10.5, 11.5, 12.0, 11.0, 10.2])
    h = A([10.2, 11.2, 12.2, 12.1, 11.1, 10.3])
    lo = A([9.8, 10.4, 11.4, 11.0, 10.1, 9.5])
    return o, h, lo


def test_hold_keeps_the_original_stop_and_exits_at_the_close():
    o, h, lo = _bars()
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "hold") == (10.4, False, 6)


def test_breakeven_moves_the_stop_to_entry_after_trigger():
    o, h, lo = _bars()
    # up 1R (high 11.2) in minute 1 -> stop 10.0 from minute 2; minute 5 low 9.5 hits it
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "breakeven", 1.0) == (10.0, True, 5)
    # a +3R trigger is never reached: behaves like hold
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "breakeven", 3.0)[1] is False


def test_trail_follows_the_best_price_and_gaps_fill_at_the_open():
    o, h, lo = _bars()
    # best 12.2 (minute 2) -> stop 11.7 from minute 3; minute 3 low 11.0 -> exit at 11.7
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "trail", 0.5) == (11.7, True, 3)
    # trail 1R: stop 11.2 after minute 2; minute 3 low 11.0 -> exit at 11.2
    px, stopped, i = I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "trail", 1.0)
    assert (px, stopped, i) == (pytest.approx(11.2), True, 3)


def test_fill_minute_never_moves_the_stop_and_short_mirrors():
    o, h, lo = (
        A([10.0, 9.0]),
        A([10.1, 9.2]),
        A([8.5, 8.9]),
    )  # fill minute already -1.5R for a short
    px, stopped, i = I.manage_exit(o, h, lo, 0, 10.0, -1, 1.0, 9.1, "breakeven", 1.0)
    assert (px, stopped, i) == (9.1, False, 2)  # the stop only starts moving after minute 0


def test_select_takes_best_ranked_candidate_after_filters():
    d = pd.Timestamp("2024-03-01")
    trades = pd.DataFrame({"date": [d, d, d], "rank": [1, 2, 3], "side": [-1, 1, 1],
                           "relvol": [9.0, 6.0, 2.0], "triggered": [True, True, True]})  # fmt: skip
    base = I.select(trades, I.Idea("b", "b"), pd.Series({d: 1}))
    assert list(base["rank"]) == [1]
    market = I.select(trades, I.Idea("m", "m", with_market=True), pd.Series({d: 1}))
    assert list(market["rank"]) == [2]  # rank 1 is short against an up market
    assert I.select(trades, I.Idea("r", "r", min_relvol=10), pd.Series({d: 1})).empty


def test_verdicts_and_family_rule():
    rows = {
        "baseline": {"family": "baseline", "Sharpe 2021-23": 0.5, "Sharpe 2024-26": 0.5},
        "a1": {"family": "a", "Sharpe 2021-23": 0.6, "Sharpe 2024-26": 0.6},  # passes
        "a2": {"family": "a", "Sharpe 2021-23": 0.7, "Sharpe 2024-26": 0.4},  # one half only
        "a3": {"family": "a", "Sharpe 2021-23": 0.6, "Sharpe 2024-26": 0.9},  # passes
        "b1": {"family": "b", "Sharpe 2021-23": 0.6, "Sharpe 2024-26": 0.6},
        "b2": {"family": "b", "Sharpe 2021-23": 0.6, "Sharpe 2024-26": 0.6},
        "b3": {"family": "b", "Sharpe 2021-23": 0.1, "Sharpe 2024-26": 0.6},
        "c": {"family": "c", "Sharpe 2021-23": 0.9, "Sharpe 2024-26": 0.9},
    }
    t = I.verdicts(pd.DataFrame(rows).T)
    assert t.loc["baseline", "passes"] == "-"
    assert t.loc["a1", "passes"] is True and t.loc["a2", "passes"] is False
    # a: two pass but the middle (a2) fails -> fail; b: two pass incl. the middle -> PASS
    assert I.family_verdict(t) == {"a": "fail", "b": "PASS", "c": "PASS"}


def test_fill_minute_check_can_be_skipped_when_seconds_were_checked():
    o, h, lo = _bars()
    # the fill minute's low (9.8) would stop a 0.1R-wide stop, but the seconds said no
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 0.1, 10.4, "hold")[1] is True
    px, stopped, i = I.manage_exit(o, h, lo, 0, 10.0, 1, 0.1, 10.4, "hold", check_fill_minute=False)
    assert (stopped, i) == (True, 5)  # later minute 5 (low 9.5) still stops it


def test_target_exits_at_the_limit_or_a_better_gap():
    o, h, lo = _bars()
    # target +2R = 12.0: minute 2 trades through (high 12.2) -> exit at 12.0 in minute 2
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "target", 2.0) == (12.0, False, 2)
    # target +1R = 11.0: minute 1 high 11.2 -> 11.0; a touch without trading through doesn't fill
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "target", 1.0) == (11.0, False, 1)
    assert I.manage_exit(o, h, lo, 0, 10.0, 1, 1.0, 10.4, "target", 2.2)[2] == 6  # 12.2 = no fill
    # a gap above the target fills at the (better) open
    o2, h2, lo2 = A([10.0, 12.5]), A([10.1, 12.6]), A([9.9, 12.4])
    assert I.manage_exit(o2, h2, lo2, 0, 10.0, 1, 1.0, 10.4, "target", 2.0) == (12.5, False, 1)


def test_volatility_regime_has_no_lookahead():
    from horizon_trader.intraday import features as F

    rng = np.random.default_rng(4)
    idx = pd.bdate_range("2019-01-01", periods=700)
    close = pd.Series(
        100 * np.cumprod(1 + rng.normal(0, 0.01, 700) * np.linspace(0.5, 2, 700)), idx
    )
    full = F.volatility_regime(close, window=20, lookback=252)
    assert full.iloc[:272].isna().all() and full.dropna().isin([-1, 1]).all()
    for t in (300, 450, 699):  # cutting off the future doesn't change day t
        assert F.volatility_regime(close.iloc[: t + 1], 20, 252).iloc[t] == full.iloc[t]
    assert (full.iloc[-50:] == 1).mean() > 0.8  # volatility rises through the sample


def test_gap_and_regime_filters_in_selection():
    d1, d2 = pd.Timestamp("2024-03-01"), pd.Timestamp("2024-03-04")
    trades = pd.DataFrame(
        {
            "date": [d1, d1, d2],
            "rank": [1, 2, 1],
            "side": [1, 1, -1],
            "relvol": [9.0, 6.0, 5.0],
            "triggered": True,
            "open": [10.1, 10.6, 9.0],
            "prev_close": [10.0, 10.0, 10.0],
        }
    )
    # gaps: +1%, +6%, -10%
    big = I.select(trades, I.Idea("g", "g", min_gap=0.04), pd.Series(dtype=int))
    assert list(zip(big.date, big["rank"], strict=True)) == [(d1, 2), (d2, 1)]
    agree = I.select(trades, I.Idea("a", "a", gap_agrees=True), pd.Series(dtype=int))
    assert len(agree) == 2  # d1 rank 1 (up gap, long), d2 (down gap, short)
    regime = pd.Series({d1: 1.0, d2: -1.0})
    high = I.select(trades, I.Idea("h", "h", vol_regime=1), pd.Series(dtype=int), regime)
    assert list(high.date) == [d1]
