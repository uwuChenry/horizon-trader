from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import orb_exit_diagnostics as D

T0 = pd.Timestamp("2024-03-01 10:00", tz="America/New_York")


def trade(**kwargs):
    return SimpleNamespace(
        **(
            {
                "side": 1,
                "entry_px": 100,
                "stop_dist": 2,
                "entry_time": T0 - pd.Timedelta(minutes=5),
                "exit_time": T0,
                "exit_px_cons": 101,
                "exit_reason": "ema",
                "gross_R": 0.5,
            }
            | kwargs
        )
    )


def bars():
    return pd.DataFrame(
        {
            "ts": pd.date_range(T0, periods=3, freq="min"),
            "open": [101, 100, 100],
            "high": [101.5, 103, 110],
            "low": [100, 97, 99],
        }
    )


def test_continuation_bounds_exclude_post_stop_rally_and_unknown_stop_bar_order():
    control = trade(exit_reason="stop", exit_time=T0 + pd.Timedelta(minutes=1), gross_R=-1)
    result = D.continuation(bars(), trade(), control, close_px=109)
    assert result["later_favorable_R"] == 4.5  # later 110, ignoring the stop
    assert result["before_stop_favorable_R_lower"] == 0.25  # only the first bar
    assert result["before_stop_favorable_R_upper"] == 1  # 103 and stop in same minute


def test_gap_stop_does_not_credit_later_stop_minute_high():
    b = bars()
    b.loc[1, "open"] = 97
    control = trade(exit_reason="stop", exit_time=T0 + pd.Timedelta(minutes=1))
    result = D.continuation(b, trade(), control, 109)
    assert result["before_stop_favorable_R_lower"] == 0.25
    assert result["before_stop_favorable_R_upper"] == 0.25


def test_short_continuation_mirrors_long():
    b = bars()
    reflected = b.assign(open=200 - b.open, high=200 - b.low, low=200 - b.high)
    control = trade(exit_reason="stop", exit_time=T0 + pd.Timedelta(minutes=1), gross_R=-1)
    long = D.continuation(b, trade(), control, 109)
    short = D.continuation(
        reflected,
        trade(side=-1, exit_px_cons=99),
        trade(side=-1, exit_reason="stop", exit_time=control.exit_time, gross_R=-1),
        91,
    )
    assert long == short


def test_close_auction_included_when_better_than_last_minute():
    control = trade(exit_reason="close", exit_time=T0 + pd.Timedelta(minutes=3))
    result = D.continuation(bars(), trade(), control, close_px=115)
    assert result["before_stop_favorable_R_lower"] == 7
    assert result["before_stop_favorable_R_upper"] == 7


def test_stop_recovery_excludes_unknown_prices_in_stopping_minute():
    b = bars().iloc[:2].copy()
    b.loc[1, ["open", "high", "low"]] = [98, 99, 97]
    stopped = trade(exit_reason="stop", exit_px_cons=98)
    result = D.stop_recovery(b, stopped, 99)
    assert not result["later_reclaims_entry"]
    assert not result["close_beyond_entry"]
    assert result["hypothetical_unstopped_close_R"] == -0.5


def test_timing_denominators_and_boundaries():
    rows = [
        vars(trade(exit_time=T0 + pd.Timedelta(minutes=n), entry_time=T0, exit_reason=reason))
        for n, reason in ((0, "stop"), (5, "stop"), (30, "stop"), (20, "ema"))
    ]
    out = D.stop_timing(pd.DataFrame(rows), "test")
    age = out[out.axis == "elapsed"].set_index("bucket")
    assert age.loc["<5 min", "fraction_of_stops"] == pytest.approx(1 / 3)
    assert age.loc["<5 min", "fraction_of_trades"] == 0.25
    assert age.loc["5-15 min", "at_risk_at_bin_start"] == 3
    assert age.loc["30-60 min", "conditional_stop_fraction"] == 1


def test_paired_costs_retain_same_quantity_and_charge_ema_exit_slippage():
    a = trade(exit_reason="ema", exit_px_cons=101)
    b = trade(exit_reason="close", exit_px_cons=101)
    # Identical price, quantity and Tiered schedule. EMA exit pays another cent,
    # offset by slightly lower regulatory sale fees on the long exit.
    difference = D.net_result(b, 25) - D.net_result(a, 25)
    assert difference == pytest.approx(0.25 * (1 - D.orb.SEC_FEE))


def test_block_ratio_keeps_flat_sessions_and_denominator_counts():
    daily = pd.DataFrame({"event": [1, 0] * 30, "trade": [1, 0] * 30})
    result = D.block_intervals(daily, {"always": ("event", "trade")}, samples=50)
    np.testing.assert_allclose(result[["estimate", "ci95_low", "ci95_high"]], 1)
