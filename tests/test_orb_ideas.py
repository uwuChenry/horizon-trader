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
