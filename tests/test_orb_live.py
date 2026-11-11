from datetime import date

import numpy as np
import pandas as pd
import pytest

from horizon_trader.intraday import features as F
from horizon_trader.intraday.orb_live import (
    ACCOUNT,
    RULES,
    bracket,
    pick,
    plan_trade,
    todays_features,
)

DAYS = pd.bdate_range("2026-01-05", periods=16)  # 15 days of history + "today"
TODAY = DAYS[-1].date()


def make_data():
    rng = np.random.default_rng(1)
    cols = ["AAA", "BBB"]
    close = pd.DataFrame(rng.uniform(20, 30, (16, 2)), index=DAYS, columns=cols)
    panels = {
        "open": close - 0.2,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": pd.DataFrame(rng.uniform(2e6, 3e6, (16, 2)), index=DAYS, columns=cols),
    }
    or_volume = pd.DataFrame(rng.uniform(1e5, 2e5, (16, 2)), index=DAYS, columns=cols)
    # BBB splits 2-for-1 effective today: history must be restated in today's share basis
    splits = pd.DataFrame(
        {"ticker": ["BBB"], "execution_date": [DAYS[-1]], "split_from": [1], "split_to": [2]}
    )
    return panels, or_volume, splits


def test_live_relvol_matches_the_backtest_including_a_split_today():
    panels, or_volume, splits = make_data()
    history = {k: v.iloc[:-1] for k, v in panels.items()}  # live: today's bars don't exist yet
    feats = todays_features(history, or_volume.iloc[:-1], splits, TODAY)

    factor = F.split_factors(DAYS, panels["open"].columns, splits)
    traded = panels["volume"] > 0
    backtest = F.relative_volume(or_volume, factor, traded, RULES.lookback).iloc[-1]
    live = or_volume.iloc[-1] / feats["or_vol_mean"]
    pd.testing.assert_series_equal(live, backtest, check_names=False)

    expected = F.daily_features(panels, factor, RULES.lookback)
    for col in ("atr", "avg_volume", "prev_close"):
        pd.testing.assert_series_equal(feats[col], expected[col].iloc[-1], check_names=False)
    assert feats.loc["BBB", "prev_close"] == pytest.approx(panels["close"].iloc[-2]["BBB"] / 2)


def test_pick_ranks_by_relvol_and_applies_the_filters():
    feats = pd.DataFrame(
        {"atr": [1.0, 1.0, 0.2], "avg_volume": [2e6, 2e6, 2e6], "prev_close": [20.0] * 3,
         "or_vol_mean": [100.0, 100.0, 100.0]},
        index=["AAA", "BBB", "CCC"],
    )  # fmt: skip
    ors = pd.DataFrame(
        {"or_open": [20.0, 20.0, 20.0], "or_high": [21.0, 21.0, 21.0], "or_low": [19.5] * 3,
         "or_close": [19.8, 20.5, 20.5], "or_volume": [300.0, 500.0, 900.0],
         "opens_on_time": [True] * 3},
        index=["AAA", "BBB", "CCC"],
    )  # fmt: skip
    c = pick(feats, ors)
    assert list(c.index) == ["BBB", "AAA"]  # CCC fails the $0.50 ATR filter
    assert c.loc["BBB", "side"] == 1 and c.loc["AAA", "side"] == -1


def test_plan_sizes_by_risk_then_leverage():
    c = pd.Series(
        {"side": 1, "or_high": 50.0, "or_low": 48.0, "atr": 2.0, "relvol": 9.0}, name="AAA"
    )
    plan = plan_trade(c, 5_000.0)
    assert plan.qty == 25 and plan.level == 50.0 and plan.stop_px == 48.0  # $50 risk / $2
    tight = plan_trade(c.copy().replace({2.0: 0.05}), 5_000.0)  # risk would allow 1,000 shares
    assert tight.qty == ACCOUNT.leverage * 5_000 / 50  # 4x cap: 400 shares
    short = plan_trade(c.copy().replace({1: -1}), 5_000.0)
    assert short.level == 48.0 and short.stop_px == 50.0


def test_bracket_is_entry_plus_attached_stop_and_no_moc():
    c = pd.Series({"side": -1, "or_high": 50.0, "or_low": 48.0, "atr": 2.0, "relvol": 9.0},
                  name="AAA")  # fmt: skip
    entry, stop = bracket(plan_trade(c, 5_000.0), "DU1", (7, 8), date(2026, 1, 26))
    assert (entry.action, entry.orderType, entry.auxPrice, entry.lmtPrice) == (
        "SELL", "STP LMT", 48.0, 48.0)  # fmt: skip
    assert entry.tif == "GTD" and entry.goodTillDate == "20260126 15:44:00 US/Eastern"
    assert (stop.action, stop.orderType, stop.auxPrice, stop.parentId) == ("BUY", "STP", 50.0, 7)
    assert stop.ocaGroup == ""  # IBKR rejected MOC in an OCA group (Invalid OCA handling method)
    assert [o.transmit for o in (entry, stop)] == [False, True]
    assert {o.orderRef for o in (entry, stop)} == {"orb"}
    assert {o.account for o in (entry, stop)} == {"DU1"}


class _Status:
    def __init__(self, status="Submitted"):
        self.status = status


class _Trade:
    def __init__(self, order, status="Submitted", done=False):
        self.order, self.orderStatus, self.log, self.done = order, _Status(status), [], done

    def isDone(self):
        return self.done


class FakeIB:
    """Positions by time step; records orders; ib.sleep just advances."""

    def __init__(self, positions, reject=()):
        self.positions_seq = list(positions)
        self.placed, self.cancelled, self.reject = [], [], set(reject)

    def isConnected(self):
        return True

    def sleep(self, s):
        pass

    def reqPositions(self):
        held = self.positions_seq.pop(0) if len(self.positions_seq) > 1 else self.positions_seq[0]
        from types import SimpleNamespace as NS

        return [NS(account="DU1", contract=NS(conId=1), position=held),
                NS(account="DU1", contract=NS(conId=2), position=99)]  # fmt: skip

    def placeOrder(self, contract, order):
        status = "Inactive" if order.orderType in self.reject else "PreSubmitted"
        t = _Trade(order, status)
        self.placed.append(order)
        return t

    def cancelOrder(self, order):
        self.cancelled.append(order)
        for t in self.trades:
            if t.order is order:
                t.done = True


def _manage(monkeypatch, ib, trades=None):
    from types import SimpleNamespace as NS

    from horizon_trader.intraday import orb_live as OL

    monkeypatch.setattr(OL, "_wait_until", lambda *a, **k: None)
    alerts = []
    monkeypatch.setattr(OL, "alert", lambda *a: alerts.append(a))
    log = {}
    trades = trades if trades is not None else [_Trade(NS(orderType="STP LMT"), done=True),
                                                _Trade(NS(orderType="STP"))]  # fmt: skip
    ib.trades = trades
    OL.manage_exit(ib, "DU1", NS(conId=1, symbol="AAA"), trades, TODAY, log, lambda: None)
    return log, alerts, trades


def test_exit_reads_the_real_position_and_sends_moc(monkeypatch):
    ib = FakeIB([48, 0])
    log, alerts, trades = _manage(monkeypatch, ib)
    assert ib.cancelled == [trades[1].order]  # working stop cancelled, done entry left alone
    (moc,) = ib.placed
    assert (moc.action, moc.totalQuantity, moc.orderType) == ("SELL", 48, "MOC")
    assert moc.orderRef == "orb"
    assert log["exit"]["position_at_exit"] == 48 and log["decision"] == "closed at the close"
    assert alerts == []


def test_exit_falls_back_to_market_when_moc_rejected(monkeypatch):
    ib = FakeIB([-20, 0], reject={"MOC"})
    log, _, _ = _manage(monkeypatch, ib)
    assert [(o.orderType, o.action, o.totalQuantity) for o in ib.placed] == [
        ("MOC", "BUY", 20), ("MKT", "BUY", 20)]  # fmt: skip
    assert log["exit"]["moc"] == "Inactive"


def test_exit_when_flat_sends_nothing(monkeypatch):
    ib = FakeIB([0])
    log, alerts, _ = _manage(monkeypatch, ib)
    assert ib.placed == [] and "flat at 15:45" in log["decision"] and alerts == []


def test_not_flat_after_close_alerts(monkeypatch):
    ib = FakeIB([48, 48])
    log, alerts, _ = _manage(monkeypatch, ib)
    assert "NOT FLAT" in log["decision"] and len(alerts) == 1


def test_leftover_value_uses_prev_close():
    from horizon_trader.intraday.orb_live import leftover_value

    feats = pd.DataFrame({"prev_close": [21.0]}, index=["FA"])
    assert leftover_value({"FA": 48.0}, feats) == 48 * 21.0
    assert leftover_value({"ZZZ": 5.0}, feats) == 0.0


def test_close_order_flattens_either_side():
    from horizon_trader.intraday.orb_live import close_order

    o = close_order(-7, "DU1", "MKT", "OPG")
    assert (o.action, o.totalQuantity, o.orderType, o.tif, o.orderRef) == (
        "BUY", 7, "MKT", "OPG", "orb")  # fmt: skip
