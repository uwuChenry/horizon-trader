import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import orb_ema as E

DAY = pd.Timestamp("2024-03-01")
START = E.F.session_open(DAY.date())
END = START + E.orb.CLOSE_TIME


def bars(prices, start=START):
    p = np.array(prices, dtype=float)
    return pd.DataFrame(
        {
            "ts": pd.date_range(start, periods=len(p), freq="min"),
            "open": p,
            "high": p + 0.1,
            "low": p - 0.1,
            "close": p,
        }
    )


def signals(minutes, close, ema):
    return pd.DataFrame(
        {
            "signal_time": [START + pd.Timedelta(minutes=m) for m in minutes],
            "close": close,
            "ema": ema,
        }
    )


def candidate(**kwargs):
    return {"date": DAY, "ticker": "X", "side": 1, "atr": 2, "close": 12} | kwargs


def test_completed_candles_only_and_truncation_invariance():
    history = bars(np.linspace(8, 10, 100), START - pd.Timedelta(days=1))
    today = bars(np.linspace(10, 12, 20))
    full = E.ema_signals(history, today, E.Rules())
    for n in (3, 5, 12, 17):
        cut = E.ema_signals(history, today.iloc[:n], E.Rules())
        known = full[full.signal_time <= START + pd.Timedelta(minutes=n)]
        pd.testing.assert_frame_equal(cut, known.reset_index(drop=True))
    assert full.signal_time.iloc[-1] == START + pd.Timedelta(minutes=20)


def test_split_adjustment_does_not_use_future_splits():
    history = bars([100, 102], START - pd.Timedelta(days=1))
    splits = pd.DataFrame(
        {
            "execution_date": [DAY, DAY + pd.Timedelta(days=10)],
            "split_from": [1, 1],
            "split_to": [2, 10],
        }
    )
    adjusted = E.adjust_history(history, DAY, splits)
    assert adjusted.close.tolist() == [50, 51]
    assert history.close.tolist() == [100, 102]
    pd.testing.assert_frame_equal(adjusted, E.adjust_history(history, DAY, splits.iloc[:1]))


def test_ema_confirm_fills_at_next_open_and_exits_at_next_open():
    b = bars([10] * 10 + [11, 11, 11, 11, 11, 10.5, 10.6])
    s = signals([10, 15], [10.8, 10.6], [10.2, 10.7])
    t = E.simulate(b, s, candidate(), "orb_ema_confirm", 1, END)
    assert t["entry_idx"] == 10 and t["entry_px"] == 11
    assert t["exit_idx_cons"] == 15 and t["exit_px_cons"] == 10.5
    assert t["exit_reason"] == "ema" and not t["stopped_cons"]


def test_short_mirrors_long_even_with_opposite_opening_candle():
    b = bars([10] * 10 + [9] * 5 + [9.5])
    s = signals([10, 15], [9.2, 9.4], [9.8, 9.3])
    t = E.simulate(b, s, candidate(side=1), "orb_ema_confirm", 1, END)
    assert t["side"] == -1 and t["entry_px"] == 9
    assert t["exit_px_cons"] == 9.5 and t["exit_reason"] == "ema"


def test_stop_gaps_and_open_exit_priority_over_later_intraminute_stop():
    b = bars([10] * 5 + [11] * 5 + [10.5])
    s = signals([5, 10], [10, 10.2], [9.8, 10.4])
    b.loc[10, "low"] = 5  # happens after the EMA exit at the open
    t = E.simulate(b, s, candidate(), "selected_ema", 1, END)
    assert t["exit_px_cons"] == 10.5 and t["exit_reason"] == "ema"
    b.loc[10, "open"] = 8  # gap through the 9 stop: the protective stop wins
    t = E.simulate(b, s, candidate(), "selected_ema", 1, END)
    assert t["exit_px_cons"] == 8 and t["exit_reason"] == "stop"


def test_original_entry_unchanged_with_ema_exit_and_conservative_same_bar_stop():
    b = bars([10] * 5 + [10.2, 11, 11, 11, 11, 10.5])
    s = signals([10], [10.2], [10.4])
    base = E.simulate(b, s, candidate(), "orb", 1, END)
    managed = E.simulate(b, s, candidate(), "orb_ema_exit", 1, END)
    assert base["entry_time"] == managed["entry_time"]
    assert base["entry_px"] == managed["entry_px"] == 10.2
    assert base["exit_reason"] == "close" and managed["exit_reason"] == "ema"
    b.loc[5, "low"] = 8
    stopped = E.simulate(b, s, candidate(), "orb", 1, END)
    assert stopped["exit_idx_cons"] == 5
    assert stopped["exit_px_cons"] == pytest.approx(8.2)


def test_ema_equality_no_entry_and_no_range_confirmation_no_trade():
    b = bars([10] * 12)
    equal = signals([5, 10], [10, 10], [10, 10])
    assert E.simulate(b, equal, candidate(), "selected_ema", 1, END) is None
    inside = signals([5, 10], [10, 10], [9.8, 9.8])
    assert E.simulate(b, inside, candidate(), "orb_ema_confirm", 1, END) is None
    assert E.simulate(b, inside, candidate(), "selected_ema", 1, END) is not None


def test_no_reentry_after_exit_and_future_bars_do_not_change_closed_trade():
    b = bars([10] * 5 + [11] * 5 + [10.5] + [12] * 10)
    s = signals([5, 10, 15], [10, 10.2, 12], [9.8, 10.4, 11])
    full = E.simulate(b, s, candidate(), "selected_ema", 1, END)
    cut = E.simulate(b.iloc[:11], s.iloc[:2], candidate(), "selected_ema", 1, END)
    assert full == cut
    assert full["exit_idx_cons"] == 10


def test_early_close_excludes_afternoon_signals_and_fills():
    end = START + pd.Timedelta(minutes=210)
    b = bars([10] * 211)
    s = signals([210], [11], [10])
    assert E.simulate(b, s, candidate(), "selected_ema", 1, end) is None
    assert E.session_end(b, DAY) == end


def test_costs_include_ema_exit_slippage_keep_flat_days_and_size_whole_shares():
    b = bars([10] * 5 + [11] * 5 + [10.5])
    s = signals([5, 10], [10, 10.2], [9.8, 10.4])
    t = pd.DataFrame([E.simulate(b, s, candidate(), "selected_ema", 1, END)])
    cal = pd.bdate_range(DAY, periods=3)
    equity, fills = E.portfolio(t, cal, "none", 0.05)
    assert len(equity) == 4 and equity.iloc[-1] == equity.iloc[1]
    assert fills.qty.iloc[0] == 25
    assert fills.entry_fill.iloc[0] == pytest.approx(11.05)
    assert fills.exit_fill.iloc[0] == pytest.approx(10.45)
    assert fills.pnl.iloc[0] == pytest.approx(-15)
    _, charged = E.portfolio(t, cal, "fixed", 0.05)
    assert charged.pnl.iloc[0] < fills.pnl.iloc[0] - 2


def test_empty_trades_produce_flat_curve():
    b = bars([10] * 5 + [11])
    t = pd.DataFrame([E.simulate(b, signals([], [], []), candidate(), "orb", 1, END)])
    curve, fills = E.portfolio(t.iloc[:0], pd.bdate_range(DAY, periods=3), "fixed", 0.05)
    assert (curve == 5000).all() and fills.empty


def test_fifteen_minute_ema_uses_fifteen_minute_closes_and_is_causal():
    history = bars(np.linspace(8, 10, 390), START - pd.Timedelta(days=1))
    today = bars(np.linspace(10, 12, 45))
    rules = E.Rules(candle_minutes=15)
    full = E.ema_signals(history, today, rules)
    expected = pd.concat([history.close.iloc[14::15], today.close.iloc[14::15]])
    expected = expected.ewm(span=12, adjust=False, min_periods=12).mean()
    np.testing.assert_allclose(full.ema, expected, equal_nan=True)
    assert full[full.signal_time > START].signal_time.tolist() == [
        START + pd.Timedelta(minutes=m) for m in (15, 30, 45)
    ]
    for n in (5, 14, 15, 29, 30, 44):
        cut = E.ema_signals(history, today.iloc[:n], rules)
        known = full[full.signal_time <= START + pd.Timedelta(minutes=n)]
        pd.testing.assert_frame_equal(cut, known.reset_index(drop=True))


@pytest.mark.parametrize("side", [1, -1])
@pytest.mark.parametrize("variant", ["orb_ema_exit", "orb_ema_confirm", "selected_ema"])
def test_slow_exit_keeps_fast_entry_and_ignores_intermediate_fast_exit(side, variant):
    b = bars([10] * 5 + [10 + side] * 10 + [10 + 0.5 * side])
    fast = signals([5, 10, 15], [10 + 0.2 * side, 10 - side, 10 - side], [10] * 3)
    slow = signals([15], [10 - side], [10])
    old = E.simulate(b, fast, candidate(side=side), variant, 1, END)
    new = E.simulate(b, fast, candidate(side=side), variant, 1, END, exit_signals=slow)
    assert old["entry_time"] == new["entry_time"] == START + pd.Timedelta(minutes=5)
    assert old["entry_px"] == new["entry_px"] == 10 + side
    assert old["exit_idx_cons"] == 10 and new["exit_idx_cons"] == 15
    assert new["exit_reason"] == "ema"


def test_stop_is_active_before_the_first_fifteen_minute_close():
    b = bars([10] * 5 + [11, 11, 8] + [10] * 8)
    fast = signals([5, 10], [10.2, 10], [10, 10])
    slow = signals([15], [9], [10])
    t = E.simulate(b, fast, candidate(), "orb_ema_exit", 1, END, exit_signals=slow)
    assert t["exit_reason"] == "stop" and t["exit_idx_cons"] == 7
    assert t["exit_px_cons"] == 8


def test_fifteen_minute_exit_waits_for_observed_open_if_next_minute_is_missing():
    b = bars([10] * 5 + [11] * 10 + [10.5, 10.6]).drop(index=15)
    fast = signals([5], [10.2], [10])
    slow = signals([15], [9], [10])
    t = E.simulate(b, fast, candidate(), "orb_ema_exit", 1, END, exit_signals=slow)
    assert t["exit_reason"] == "ema"
    assert t["exit_time"] == START + pd.Timedelta(minutes=16)
    assert t["exit_px_cons"] == 10.6


@pytest.mark.parametrize("side", [1, -1])
def test_tiered_one_cent_charges_both_market_fills(side):
    b = bars([10] * 5 + [10 + side] * 10 + [10 + 0.5 * side])
    fast = signals([5], [10 + 0.2 * side], [10])
    slow = signals([15], [10 - side], [10])
    t = pd.DataFrame(
        [E.simulate(b, fast, candidate(side=side), "selected_ema", 1, END, exit_signals=slow)]
    )
    _, fills = E.portfolio(t, pd.bdate_range(DAY, periods=3), "tiered", 0.01)
    assert fills.qty.iloc[0] == 25
    entry, exit_ = 10 + side + side * 0.01, 10 + 0.5 * side - side * 0.01
    assert fills.entry_fill.iloc[0] == pytest.approx(entry)
    assert fills.exit_fill.iloc[0] == pytest.approx(exit_)
    model = E.orb.PLANS["tiered"]
    expected_cost = model.total(25 * side, entry) + model.total(-25 * side, exit_)
    assert fills.costs.iloc[0] == pytest.approx(expected_cost)
    assert fills.pnl.iloc[0] == pytest.approx(25 * side * (exit_ - entry) - expected_cost)


@pytest.mark.parametrize("side", [1, -1])
def test_two_adverse_fifteen_minute_closes_required_and_future_cannot_change_exit(side):
    b = bars([10] * 5 + [10 + side] * 60)
    s = signals([15, 30, 45], [10 - side] * 3, [10] * 3)
    rules = E.Rules(exit_candle_minutes=15, exit_confirmations=2)
    full = E.simulate(b, s, candidate(side=side), "orb_ema_exit", 1, END, rules, s)
    cut = E.simulate(
        b.iloc[:31], s.iloc[:2], candidate(side=side), "orb_ema_exit", 1, END, rules, s.iloc[:2]
    )
    assert full == cut and full["exit_idx_cons"] == 30
    assert full["exit_reason"] == "ema"


@pytest.mark.parametrize("middle_close", [10, 11])
def test_equality_or_favorable_close_resets_confirmation(middle_close):
    b = bars([10] * 5 + [11] * 60)
    s = signals([15, 30, 45, 60], [9, middle_close, 9, 9], [10] * 4)
    rules = E.Rules(exit_candle_minutes=15, exit_confirmations=2)
    t = E.simulate(b, s, candidate(), "orb_ema_exit", 1, END, rules, s)
    assert t["exit_idx_cons"] == 60


def test_missing_intervening_candle_resets_two_close_confirmation():
    b = bars([10] * 5 + [11] * 60)
    s = signals([15, 45, 60], [9] * 3, [10] * 3)
    rules = E.Rules(exit_candle_minutes=15, exit_confirmations=2)
    t = E.simulate(b, s, candidate(), "orb_ema_exit", 1, END, rules, s)
    assert t["exit_idx_cons"] == 60


def test_pre_entry_signal_cannot_count_toward_exit_confirmation():
    b = bars([10] * 16 + [11] * 31)
    # Keep bars after the opening range strictly below its high until minute 16.
    b.loc[5:15, "high"] = 10.05
    s = signals([15, 30, 45], [9] * 3, [10] * 3)
    rules = E.Rules(exit_candle_minutes=15, exit_confirmations=2)
    t = E.simulate(b, s, candidate(), "orb_ema_exit", 1, END, rules, s)
    assert t["entry_idx"] == 16 and t["exit_idx_cons"] == 45


def test_stop_remains_active_between_first_and_second_adverse_close():
    b = bars([10] * 5 + [11] * 15 + [8] + [11] * 10)
    s = signals([15, 30], [9, 9], [10, 10])
    rules = E.Rules(exit_candle_minutes=15, exit_confirmations=2)
    t = E.simulate(b, s, candidate(), "orb_ema_exit", 1, END, rules, s)
    assert t["exit_reason"] == "stop" and t["exit_idx_cons"] == 20
    assert t["exit_px_cons"] == 8


def test_two_close_confirmed_exit_uses_next_observed_open():
    b = bars([10] * 5 + [11] * 25 + [10.5, 10.6]).drop(index=30)
    s = signals([15, 30], [9, 9], [10, 10])
    rules = E.Rules(exit_candle_minutes=15, exit_confirmations=2)
    t = E.simulate(b, s, candidate(), "orb_ema_exit", 1, END, rules, s)
    assert t["exit_time"] == START + pd.Timedelta(minutes=31)
    assert t["exit_px_cons"] == 10.6


def test_half_stop_doubles_shares_at_same_risk_and_higher_risk_doubles_again():
    b = bars([19] * 5 + [20])
    c = candidate(atr=1, close=22)
    wide = pd.DataFrame([E.simulate(b, signals([], [], []), c, "orb", 1, END)])
    tight = pd.DataFrame([E.simulate(b, signals([], [], []), c, "orb", 0.5, END)])
    cal = pd.bdate_range(DAY, periods=2)
    _, a = E.portfolio(wide, cal, "none", 0, risk=0.01)
    _, z = E.portfolio(tight, cal, "none", 0, risk=0.01)
    _, more = E.portfolio(tight, cal, "none", 0, risk=0.02)
    assert (a.qty.iloc[0], z.qty.iloc[0], more.qty.iloc[0]) == (50, 100, 200)
    assert (a.pnl.iloc[0], z.pnl.iloc[0], more.pnl.iloc[0]) == (100, 200, 400)
    _, unused = E.portfolio(tight, cal, "none", 0, risk=0.01, leverage=4)
    pd.testing.assert_frame_equal(z, unused)


def test_notional_cap_limits_size_and_a_gap_can_exceed_planned_stop_risk():
    b = bars([19] * 5 + [20, 18])
    # Entry-minute lows must stay above a 10c stop in the cap test.
    b.loc[5, "low"] = 20
    c = candidate(atr=1, close=22)
    cal = pd.bdate_range(DAY, periods=2)
    t = pd.DataFrame([E.simulate(b, signals([], [], []), c, "orb", 0.1, END)])
    _, capped = E.portfolio(t, cal, "none", 0, risk=0.02, leverage=2)
    _, uncapped = E.portfolio(t, cal, "none", 0, risk=0.02, leverage=4)
    assert (capped.qty.iloc[0], uncapped.qty.iloc[0]) == (500, 1000)
    half = pd.DataFrame([E.simulate(b, signals([], [], []), c, "orb", 0.5, END)])
    _, fills = E.portfolio(half, cal, "none", 0, risk=0.01)
    assert fills.pnl.iloc[0] == -200  # Planned 50 dollars; a gap bypasses the stop.
