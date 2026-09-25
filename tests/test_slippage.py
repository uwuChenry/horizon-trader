import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import orb, slippage

T0 = pd.Timestamp("2024-03-01 09:40", tz="America/New_York")


def _secs(rows):
    ts = [T0 + pd.Timedelta(seconds=i) for i in range(len(rows))]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume", "vwap"])
    return df.assign(ts=ts)


def test_buy_stop_slippage_from_trigger_second():
    secs = _secs(
        [
            (9.95, 9.98, 9.95, 9.97, 100, 9.96),  # below the $10.00 trigger
            (9.99, 10.06, 9.99, 10.05, 500, 10.03),  # triggers here
            (10.07, 10.08, 10.06, 10.08, 300, 10.07),
        ]
    )
    s = slippage.fill_slippage(secs, direction=1, trigger=10.0, modeled=10.0)
    assert s["vwap"] == pytest.approx(0.03) and s["extreme"] == pytest.approx(0.06)
    assert s["next_open"] == pytest.approx(0.07) and s["trigger_sec_volume"] == 500


def test_sell_stop_never_fills_better_than_modeled():
    # vwap of the trigger second is above the sell trigger, but a sell stop fills at the bid
    secs = _secs([(10.2, 10.2, 9.99, 10.1, 100, 10.12), (10.0, 10.0, 9.97, 9.98, 50, 9.98)])
    s = slippage.fill_slippage(secs, direction=-1, trigger=10.0, modeled=10.0)
    assert s["vwap"] == 0.0 and s["extreme"] == pytest.approx(0.01)
    assert s["next_open"] == 0.0


def test_missing_or_disagreeing_seconds_give_nan():
    assert np.isnan(slippage.fill_slippage(_secs([]), 1, 10.0, 10.0)["vwap"])
    secs = _secs([(9.9, 9.95, 9.9, 9.9, 10, 9.92)])
    assert np.isnan(slippage.fill_slippage(secs, 1, 10.0, 10.0)["vwap"])


def test_fetch_seconds_parses_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    calls = []
    ms = int(T0.timestamp() * 1000)

    def fake(url):
        calls.append(url)
        return {"results": [{"t": ms, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 10, "vw": 1.2}]}

    a = slippage.fetch_seconds("ABC", T0, fetch=fake)
    b = slippage.fetch_seconds("ABC", T0, fetch=fake)
    assert len(calls) == 1 and "/range/1/second/" in calls[0] and "adjusted=false" in calls[0]
    assert a.ts.iloc[0] == T0 and a.equals(b)


def test_portfolio_uses_per_trade_measured_slippage():
    row = {"date": pd.Timestamp("2024-03-01"), "ticker": "A", "rank": 1, "triggered": True,
           "side": 1, "entry_px": 50.0, "stop_dist": 0.25, "exit_px_path": 49.75,
           "stopped_path": True, "entry_slip": 0.03, "exit_slip": 0.02}  # fmt: skip
    acct = orb.Account(equity=10_000, top_n=1, plan="none", slippage=None)
    _, fills = orb.run_portfolio(pd.DataFrame([row]), acct)
    assert fills.pnl.iloc[0] == pytest.approx(400 * (49.73 - 50.03))


def test_stop_limit_fills_after_trigger_within_limit():
    # trigger at $10.00 in second 1; live from second 2, whose low 10.03 trades through 10.05
    secs = _secs(
        [
            (9.95, 9.98, 9.95, 9.97, 100, 9.96),
            (9.99, 10.08, 9.99, 10.07, 500, 10.04),
            (10.07, 10.09, 10.03, 10.04, 300, 10.05),
        ]
    )
    assert slippage.limit_fill_in_seconds(secs, 1, 10.0, 10.05) == pytest.approx(10.05)
    assert slippage.limit_fill_in_seconds(secs, 1, 10.0, 10.02) is None  # ran away: no fill
    assert slippage.limit_fill_in_seconds(secs, 1, 10.0, 10.03) is None  # touch only: no fill


def test_exit_from_stop_gap_and_close():
    o, h, lo = np.array([10, 10.5, 9.0]), np.array([10.2, 10.6, 9.1]), np.array([9.95, 10.4, 8.8])
    assert slippage.exit_from(o, h, lo, 0, 10.0, 1, 0.5, 11.0) == (9.0, True, 2)  # gapped below 9.5
    assert slippage.exit_from(o, h, lo, 0, 10.0, 1, 2.0, 11.0) == (11.0, False, 3)
    assert slippage.exit_from(o, h, lo, 0, 10.0, -1, 0.5, 9.0) == (10.5, True, 1)  # short stop 10.5


def test_lite_charges_only_close_auction_exits():
    qty, px = np.array([100.0, 100.0]), np.array([50.0, 50.0])
    c = orb.trade_costs(qty, px, px, np.array([1, 1]), "lite", at_close=np.array([True, False]))
    sell_fees = 100 * 50 * orb.SEC_FEE + 100 * orb.FINRA_TAF
    assert c == pytest.approx([0.5 + sell_fees, sell_fees])
