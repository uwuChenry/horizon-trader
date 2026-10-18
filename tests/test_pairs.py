from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from horizon_trader.backtest import pairs


def bars(n=160):
    rng = np.random.default_rng(11)
    ix = pd.bdate_range("2026-01-07", periods=n)
    common = np.cumsum(rng.normal(0, 0.005, n))
    spread = 0.07 * np.sin(np.arange(n) / 8)
    close = pd.DataFrame({"A": 100 * np.exp(common + spread), "B": 100 * np.exp(common)}, index=ix)
    return {
        "close": close,
        "open": close.shift().fillna(close.iloc[0]),
        "signal": close.copy(),
        "dividend": close * 0,
        "split": close * 0 + 1,
        "volume": close * 0 + 100000,
    }


def cfg(**kw):
    return replace(pairs.PairConfig(pairs=(("A", "B"),), lookback=20), **kw)


def force_signals(monkeypatch, data, convergence=2):
    f = pd.DataFrame(
        {"spread": -2.5, "mean": 0.0, "std": 1.0, "z": -2.5, "correlation": 1.0},
        index=data["close"].index,
    )
    f.iloc[convergence:, f.columns.get_loc("spread")] = 0.0
    f.iloc[2:, f.columns.get_loc("z")] = 0.0
    monkeypatch.setattr(pairs, "make_signals", lambda b, c: {"A/B": f.loc[b["close"].index]})


def flat_data(n=5):
    b = bars(n)
    for k in ("open", "close", "signal"):
        b[k].loc[:, :] = 100.0
    return b


def test_future_truncation_changes_neither_signals_nor_trades():
    b = bars()
    c = cfg()
    short = {k: v.iloc[:115] for k, v in b.items()}
    full = pairs.simulate(b, c, str(b["close"].index[25].date()))
    cut = pairs.simulate(short, c, str(b["close"].index[25].date()))
    pd.testing.assert_frame_equal(full.daily.loc[cut.daily.index], cut.daily)
    pd.testing.assert_frame_equal(full.signals["A/B"].iloc[:115], cut.signals["A/B"])
    assert len(full.fills) > 0
    pd.testing.assert_frame_equal(full.fills[full.fills.date <= cut.daily.index[-1]], cut.fills)


def test_next_open_and_pnl_reconcile(monkeypatch):
    b = flat_data()
    force_signals(monkeypatch, b)
    b["close"].iloc[2:, 0] = 110
    b["open"].iloc[3:, 0] = 110
    c = cfg(plan="zero", slippage_bps=0, borrow_rate=0, withholding=0)
    r = pairs.simulate(b, c, str(b["close"].index[1].date()))
    assert r.fills.iloc[0].date == b["close"].index[2]
    assert (r.fills.date > r.fills.signal_date).all()
    assert r.trades.iloc[0].pnl == pytest.approx(250)
    assert r.daily.equity.iloc[-1] == pytest.approx(5250)
    assert np.equal(r.fills.quantity, np.trunc(r.fills.quantity)).all()


def test_weekend_borrow_dividend_rights_and_costs(monkeypatch):
    b = flat_data()
    force_signals(monkeypatch, b)
    # Entry Friday, exit Monday. Entry-day dividend is not owed/received.
    b["dividend"].iloc[2] = [20, 30]
    b["dividend"].iloc[3] = [2, 3]
    c = cfg(slippage_bps=5, borrow_rate=0.036, withholding=0.30)
    r = pairs.simulate(b, c, str(b["close"].index[1].date()))
    t = r.trades.iloc[0]
    assert t.dividends == pytest.approx(-25)
    assert t.withholding == pytest.approx(15)
    assert t.borrow == pytest.approx(2500 * 0.036 * 3 / 360)
    assert t.slippage == pytest.approx(5)
    assert t.commission > 1.4
    assert t.pnl == pytest.approx(t.gross - t.costs)
    assert r.daily.equity.iloc[-1] == pytest.approx(5000 + t.pnl)


def test_exit_uses_frozen_mean_not_new_rolling_mean(monkeypatch):
    b = flat_data(6)
    f = pd.DataFrame(
        {"spread": -2.5, "mean": 0.0, "std": 1.0, "z": -2.5, "correlation": 1.0},
        index=b["close"].index,
    )
    f.iloc[2:, f.columns.get_loc("mean")] = -3
    f.iloc[2:, f.columns.get_loc("z")] = 0.5  # rolling z suggests convergence, frozen doesn't
    monkeypatch.setattr(pairs, "make_signals", lambda b, c: {"A/B": f})
    r = pairs.simulate(b, cfg(), str(b["close"].index[1].date()))
    assert r.trades.empty
    assert len(r.open_positions) == 1


def test_split_has_no_free_profit(monkeypatch):
    b = flat_data()
    force_signals(monkeypatch, b)
    b["split"].iloc[3, 0] = 2
    b["open"].iloc[3:, 0] = 50
    b["close"].iloc[3:, 0] = 50
    r = pairs.simulate(
        b, cfg(plan="zero", slippage_bps=0, borrow_rate=0), str(b["close"].index[1].date())
    )
    assert r.trades.iloc[0].pnl == pytest.approx(0)
    assert r.fills.query("symbol == 'A'").quantity.tolist() == [25.0, -50.0]


def test_prepare_frame_future_splits_and_dividends():
    ix = pd.bdate_range("2026-01-01", periods=3)
    raw = pd.DataFrame(
        {
            "Open": [50.0, 50, 50],
            "Close": [50.0, 50, 50],
            "Adj Close": [49.0, 49, 50],
            "Dividends": [1.0, 0, 0],
            "Stock Splits": [0.0, 2, 0],
            "Volume": 100,
        },
        index=ix,
    )
    f = pairs.prepare_frame(raw)
    assert f.close.tolist() == [100.0, 50.0, 50.0]
    assert f.dividend.tolist() == [2.0, 0.0, 0.0]


def test_whole_share_imbalance_rejects_entry(monkeypatch):
    b = flat_data()
    b["open"].loc[:, "A"] = 1800
    b["close"].loc[:, "A"] = 1800
    force_signals(monkeypatch, b)
    r = pairs.simulate(b, cfg(), str(b["close"].index[1].date()))
    assert r.fills.empty
    assert "hedge_imbalance" in r.rejected.reason.to_list()


def test_time_stop_at_next_open(monkeypatch):
    b = flat_data(7)
    force_signals(monkeypatch, b, convergence=7)
    r = pairs.simulate(b, cfg(max_hold=2), str(b["close"].index[1].date()))
    assert r.trades.iloc[0].exit_time == b["close"].index[4]
    assert r.trades.iloc[0].held_sessions == 2
    assert r.trades.iloc[0].exit_reason == "time_stop"


def test_missing_bar_fails():
    b = bars()
    b["open"].iloc[50, 0] = np.nan
    with pytest.raises(ValueError, match="Invalid open"):
        pairs.simulate(b, cfg(), str(b["close"].index[25].date()))


@pytest.mark.parametrize("direction", [1, -1])
def test_divergence_stop_on_adverse_side(monkeypatch, direction):
    b = flat_data(5)
    f = pd.DataFrame(
        {
            "spread": -2.5 * direction,
            "mean": 0.0,
            "std": 1.0,
            "z": -2.5 * direction,
            "correlation": 1.0,
        },
        index=b["close"].index,
    )
    f.iloc[2:, f.columns.get_loc("spread")] = -4.1 * direction
    f.iloc[2:, f.columns.get_loc("z")] = 0.0
    monkeypatch.setattr(pairs, "make_signals", lambda b, c: {"A/B": f})
    r = pairs.simulate(b, cfg(), str(b["close"].index[1].date()))
    assert r.trades.iloc[0].exit_time == b["close"].index[3]
    assert r.trades.iloc[0].exit_reason == "divergence_stop"
    assert r.trades.iloc[0].side == direction


def test_dashboard_analytics_and_holdings_contract(monkeypatch):
    from horizon_trader.backtest.analytics import trade_stats
    from horizon_trader.dashboard.holdings_view import positions_at

    b = flat_data()
    force_signals(monkeypatch, b)
    r = pairs.simulate(b, cfg(), str(b["close"].index[1].date()))
    assert trade_stats(r.trades)["trades"] == 1
    held = positions_at(r.holdings, r.daily.equity, b["close"].index[2])
    assert held.shares.to_dict() == {"A": 25.0, "B": -25.0}
