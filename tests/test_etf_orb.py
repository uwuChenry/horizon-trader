import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import etf_orb as E
from horizon_trader.intraday import orb_ideas as I

DAY = pd.Timestamp("2024-03-01")
T0 = pd.Timestamp("2024-03-01 09:35", tz="America/New_York")


def _setup(o, h, lo, side=1, or_high=10.2, or_low=9.8, atr=1.0, close=10.5):
    ts = np.array([T0 + pd.Timedelta(minutes=i) for i in range(len(o))], dtype=object)
    bars = I.Bars({(DAY, "QQQ"): (ts, np.array(o), np.array(h), np.array(lo))})
    days = pd.DataFrame({"date": [DAY], "side": [side], "or_high": [or_high], "or_low": [or_low],
                         "atr": [atr], "close": [close]})  # fmt: skip
    return days, bars


RULE_A, RULE_B, RULE_C = E.RULES


def test_rule_a_enters_at_935_open_with_range_stop_and_holds_to_close():
    days, bars = _setup([10.1, 10.3, 10.4], [10.3, 10.5, 10.6], [10.0, 10.2, 10.3])
    t = E.simulate_open_entry(days, bars, "QQQ", RULE_A).iloc[0]
    assert t.entry_px == 10.1 and t.stop_dist == pytest.approx(0.3)  # 10.1 - range low 9.8
    assert t.exit_px_path == 10.5 and t.exit_reason == "close"  # 10R = 13.1 never reached


def test_rule_a_stop_and_10r_target():
    days, bars = _setup([10.1, 10.0], [10.2, 10.1], [10.0, 9.7])
    t = E.simulate_open_entry(days, bars, "QQQ", RULE_A).iloc[0]
    assert t.exit_reason == "stop" and t.exit_px_path == pytest.approx(9.8)
    days, bars = _setup([10.1, 12.0, 13.5], [10.2, 12.5, 13.2], [10.05, 11.9, 13.0], or_low=10.0)
    t = E.simulate_open_entry(days, bars, "QQQ", RULE_A).iloc[0]  # R = 0.1, target 11.1
    assert t.exit_reason == "target" and t.exit_px_path == pytest.approx(12.0)  # gap: better open


def test_rule_c_uses_five_percent_of_atr_and_short_side_mirrors():
    days, bars = _setup([9.9, 9.95, 9.7], [9.93, 10.05, 9.8], [9.85, 9.9, 9.6], side=-1, atr=2.0)
    t = E.simulate_open_entry(days, bars, "QQQ", RULE_C).iloc[0]
    assert t.stop_dist == pytest.approx(0.1)  # 5% of 2.0
    assert t.exit_reason == "stop" and t.exit_px_path == pytest.approx(10.0)  # 9.9 + 0.1, minute 1


def test_no_trade_when_the_open_is_beyond_the_far_side_of_the_range():
    days, bars = _setup([9.7, 9.8], [9.75, 9.9], [9.6, 9.7])  # long, but opens below the 9.8 low
    assert E.simulate_open_entry(days, bars, "QQQ", RULE_A).empty


def test_periods_split_at_publication_and_train_test():
    cal = pd.bdate_range("2023-01-02", "2024-06-28")
    p = E.periods(cal)
    assert p["pre-pub"][-1] < E.PUBLISHED <= p["post-pub"][0]
    assert p["train"][-1] <= pd.Timestamp("2023-12-31") < p["test"][0]
    assert len(p["all"]) == len(p["train"]) + len(p["test"])
