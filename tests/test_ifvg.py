from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import ifvg as S
from horizon_trader.intraday.ifvg_study import load_sessions, uncertainty

START = pd.Timestamp("2024-03-01 09:30", tz=S.TZ)
DAY = START.tz_localize(None).normalize()


def minute_bars(n=30, start=START):
    return pd.DataFrame(
        dict(
            ts=pd.date_range(start, periods=n, freq="min"),
            open=99.0,
            high=99.1,
            low=98.9,
            close=99.0,
        )
    )


def pattern():
    return pd.DataFrame(
        [
            (99, 100, 98, 99),
            (99, 102, 99, 101.5),
            (101.5, 103, 101, 102),
            (102, 102.5, 98.5, 99),
            (99, 100.5, 98, 99),
            (99, 100, 97, 98),
        ],
        columns=["open", "high", "low", "close"],
    ).assign(time=pd.date_range(START + 5 * S.MINUTE, periods=6, freq="5min"))


def reflect(frame):
    out = frame.copy()
    out["open"], out["close"] = 200 - frame.open, 200 - frame.close
    out["high"], out["low"] = 200 - frame.low, 200 - frame.high
    return out


def test_completed_candles_missing_minutes_and_prefix_invariance():
    b = minute_bars(35)
    b["close"] = 99 + np.arange(35) / 100
    b["high"] = b.close + 1
    full = S.candles(b)
    assert full.time.iloc[0] == START + 5 * S.MINUTE
    for n in range(1, 36):
        cut = S.candles(b.iloc[:n])
        known = full[full.time <= START + n * S.MINUTE].reset_index(drop=True)
        pd.testing.assert_frame_equal(cut, known)
    broken = S.candles(b.drop(index=2))
    assert START + 5 * S.MINUTE not in set(broken.time)
    with pytest.raises(ValueError, match="unique"):
        S.candles(pd.concat([b, b.iloc[:1]]))


@pytest.mark.parametrize("strategy", S.STRATEGIES)
def test_signal_prefix_invariance(strategy):
    b = pattern()
    full = S.signals(b, strategy)
    for n in range(1, len(b) + 1):
        assert S.signals(b.iloc[:n], strategy) == [
            s for s in full if s["signal_time"] <= b.time.iloc[n - 1]
        ]


@pytest.mark.parametrize("mirrored,side", [(False, -1), (True, 1)])
def test_inversion_requires_close_not_wick_and_is_symmetric(mirrored, side):
    b = reflect(pattern()) if mirrored else pattern()
    s = S.signals(b, "ifvg_close")[0]
    assert s["side"] == side
    assert s["formed_time"] == START + 15 * S.MINUTE
    assert s["signal_time"] == START + 20 * S.MINUTE
    b.loc[3, "close"] = 100  # equality at far edge, even though the wick crossed
    assert not S.signals(b.iloc[:4], "ifvg_close")
    assert not S.signals(b.iloc[:3], "ifvg_close")


def test_retest_must_be_later_and_must_reject_not_merely_touch():
    b = pattern()
    assert S.signals(b, "ifvg_retest")[0]["signal_time"] == START + 25 * S.MINUTE
    assert not S.signals(b.iloc[:4], "ifvg_retest")
    b.loc[4, "close"] = 100.2
    assert not S.signals(b.iloc[:5], "ifvg_retest")
    b.loc[4, "close"] = 101.2  # crosses far edge, cancels
    b.loc[4, "high"] = 101.3
    assert not S.signals(b, "ifvg_retest")


def test_age_cutoff_and_missing_candle_prevent_stale_signals():
    b = pattern()
    b.loc[3, "close"] = 100.2
    assert not S.signals(b.iloc[:5], "ifvg_close", replace(S.DEFAULT_RULES, gap_age=1))
    assert not S.signals(pattern(), "ifvg_close", replace(S.DEFAULT_RULES, last_minute=15))
    assert not S.signals(pattern().drop(index=1), "ifvg_close")
    b = pattern()
    b.loc[4, "high"] = 99.5  # no retest during the one-bar allowance
    assert not S.signals(b, "ifvg_retest", replace(S.DEFAULT_RULES, retest_age=1))


def test_most_recent_of_multiple_inverted_gaps_wins():
    b = pattern()
    # First gap forms at 09:45; another bullish gap [102, 103] at 09:50.
    b.loc[3, ["open", "high", "low", "close"]] = [103.5, 105, 103, 104]
    s = S.signals(b, "ifvg_close")[0]
    assert s["lower"] == 102 and s["upper"] == 103
    assert s["formed_time"] == START + 20 * S.MINUTE


@pytest.mark.parametrize("mirrored,side", [(False, -1), (True, 1)])
def test_next_open_entry_target_and_one_trade_only(mirrored, side):
    b, p = minute_bars(), pattern()
    b.loc[21, ["open", "high", "low", "close"]] = [99, 100, 94, 95]
    if mirrored:
        b, p = reflect(b), reflect(p)
    t = S.simulate_day(b, S.signals(p, "ifvg_close"), "ifvg_close", 2, START + 29 * S.MINUTE)
    assert t["side"] == side
    assert t["entry_time"] == START + 20 * S.MINUTE
    assert t["entry_px"] == (101 if mirrored else 99)
    assert t["exit_time"] == START + 21 * S.MINUTE
    assert t["exit_reason"] == "target"
    assert t["gross_R"] == pytest.approx(2)
    assert (
        S.simulate_day(
            b.iloc[:22], S.signals(p, "ifvg_close"), "ifvg_close", 2, START + 29 * S.MINUTE
        )
        == t
    )
    assert (
        S.simulate_day(
            b.iloc[:21], S.signals(p, "ifvg_close"), "ifvg_close", 2, START + 29 * S.MINUTE
        )
        is None
    )


@pytest.mark.parametrize("side", [-1, 1])
def test_entry_minute_both_barriers_is_stop_first(side):
    b = minute_bars(1)
    b.loc[0, ["high", "low"]] = [110, 90]
    stop, target = (101, 95) if side == -1 else (97, 103)
    out = S.exit_path(b, 0, side, stop, target, START + S.MINUTE)
    assert out["exit_px"] == stop and out["ambiguous"] and out["exit_reason"] == "stop"


def test_gap_stops_target_gap_and_scheduled_open_precede_later_extremes():
    b = minute_bars(1)
    b.loc[0, ["open", "high", "low"]] = [104, 110, 90]
    assert S.exit_path(b, 0, -1, 101, 95, START + S.MINUTE)["exit_px"] == 104
    b.loc[0, "open"] = 94
    assert S.exit_path(b, 0, -1, 101, 95, START + S.MINUTE)["exit_px"] == 95
    b.loc[0, "open"] = 99
    out = S.exit_path(b, 0, -1, 101, 95, START)
    assert out["exit_px"] == 99 and out["exit_reason"] == "session_end"


def test_invalid_entry_open_and_missing_open_are_not_filled():
    b = minute_bars()
    decisions = S.signals(pattern().iloc[:4], "ifvg_close")
    b.loc[20, "open"] = 102
    assert S.simulate_day(b, decisions, "ifvg_close", 2, START + 29 * S.MINUTE) is None
    assert (
        S.simulate_day(b.drop(index=20), decisions, "ifvg_close", 2, START + 29 * S.MINUTE) is None
    )


def test_account_cost_reconciliation_risk_budget_and_flat_days():
    b = minute_bars()
    b.loc[21, ["high", "low", "close"]] = [100, 94, 95]
    t = S.simulate_day(
        b, S.signals(pattern(), "ifvg_close"), "ifvg_close", 2, START + 29 * S.MINUTE
    )
    calendar = pd.bdate_range(DAY, periods=4)
    daily, fills = S.account(pd.DataFrame([t]), calendar, "net")
    f = fills.iloc[0]
    assert len(daily) == 4 and (daily.equity == daily.equity.iloc[0]).all()
    assert f.qty == int(f.qty) and f.planned_loss <= 50
    assert f.qty * f.entry_fill < 5000
    assert f.entry_fill == pytest.approx(t["entry_px"] - 0.01)
    assert f.exit_fill == pytest.approx(t["exit_px"] + 0.01)
    assert f.pnl == pytest.approx(f.gross_pnl - f.slippage - f.fees)
    assert f.equity_after == pytest.approx(5000 + f.pnl)
    assert daily["return"].iloc[0] == pytest.approx(f.pnl / 5000)
    assert S.metrics(daily, fills)["trades"] == 1
    _, stress = S.account(pd.DataFrame([t]), calendar, "stress")
    assert stress.slippage.iloc[0] >= f.slippage


def test_empty_account_and_first_day_drawdown_are_not_dropped():
    calendar = pd.bdate_range(DAY, periods=4)
    daily, fills = S.account(pd.DataFrame(), calendar, "net")
    assert (daily.equity == 5000).all() and fills.empty
    daily.loc[:, "equity"] = 4900
    daily.loc[0, "return"] = -0.02
    assert S.metrics(daily, fills)["max_drawdown"] == pytest.approx(-0.02)


def test_complete_half_day_qc_and_common_exclusion(tmp_path):
    root = tmp_path / "massive" / "derived"
    root.mkdir(parents=True)
    day1 = minute_bars(210)
    day2 = minute_bars(390, START + pd.Timedelta(days=3))
    for ticker in ("SPY", "QQQ"):
        b = pd.concat([day1, day2], ignore_index=True)
        if ticker == "QQQ":
            b = b.drop(index=220)
        b.to_parquet(root / f"minute_{ticker}.parquet")
    sessions, calendar, skipped, _ = load_sessions(tmp_path)
    assert list(calendar) == [DAY]
    assert sessions[DAY][1] == START + 209 * S.MINUTE
    assert skipped.iloc[0].ticker == "QQQ"


def test_bootstrap_uses_paired_dates_and_zero_days():
    dates = pd.bdate_range(DAY, periods=60)
    rows = []
    for strategy in S.STRATEGIES:
        rows.extend(
            dict(
                date=d,
                ticker="SPY",
                strategy=strategy,
                period="all",
                cost_case="net",
                target_r=2,
                **{"return": 0.001 if i % 3 else 0},
            )
            for i, d in enumerate(dates)
        )
    out = uncertainty(pd.DataFrame(rows), samples=100)
    paired = out[out.comparison != "zero"]
    assert (paired[["mean_daily_bps", "ci95_low_bps", "ci95_high_bps"]] == 0).all().all()
