"""Offline ORB paper mechanics: scripted fills, cancellation races and crash recovery."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, replace
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from alpaca.common.exceptions import APIError
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLimitOrderRequest,
    StopOrderRequest,
)

from horizon_trader.execution.alpaca_book import kill_switch_path
from horizon_trader.execution.alpaca_broker import (
    FINAL,
    AlpacaPaper,
    Leg,
    LegFill,
    OrderInfo,
    OrderSpec,
    order_request,
)
from horizon_trader.execution.ibkr_broker import GuardError
from horizon_trader.execution.ledger import Ledger
from horizon_trader.intraday import orb_alpaca as OA
from horizon_trader.intraday.orb_alpaca import plan_day as default_plan_day

DAY = "2026-11-06"
PLAN = OA.Plan("AAA", 1, 100.0, 98.0, 10, 2.0, 5.0)


def ts(hhmmss):
    return pd.Timestamp(f"{DAY} {hhmmss}", tz=OA.NY)


class FakeClock:
    def __init__(self, start="15:43:50"):
        self.t = ts(start)
        self.hook = None

    def now(self):
        return self.t

    def sleep(self, seconds):
        assert seconds >= 0
        self.t += pd.Timedelta(seconds=seconds)
        if self.hook:
            self.hook()


class FakeAlpaca:
    """Cumulative entry/stop fills on the fake clock; cancellation can be asynchronous."""

    def __init__(self, clock):
        self.clock = clock
        self.account_id = "PA9"
        self.calendar = ("09:30", "16:00")
        self.flags = dict(tradable=True, shortable=True, easy_to_borrow=True)
        self.orders, self.specs, self.sent, self.cancelled = {}, {}, [], []
        self.held = {}
        self.entry_fills = [(clock.now() + pd.Timedelta(seconds=2), 10, 100.0)]
        self.stop_fills = {}  # tag -> [(time, cumulative qty, average price)]
        self.cancel_delay = 0
        self.cancel_at = {}
        self.reject = set()
        self.close_fills = True

    def session(self, day):
        assert day == DAY
        return self.calendar

    def account(self):
        return {"account": self.account_id}

    def asset(self, ticker):
        assert ticker == PLAN.ticker
        return self.flags

    def positions(self):
        self._update()
        return dict(self.held)

    def tag(self, cid):
        return cid.split(f"orba-{DAY}-")[1]

    def _fill(self, cid, qty, price):
        info, spec = self.orders[cid], self.specs[cid]
        leg = spec.legs[0]
        delta = qty - info.filled_qty
        signed = delta * (1 if leg.side == "buy" else -1)
        self.held[leg.symbol] = self.held.get(leg.symbol, 0) + signed
        if not self.held[leg.symbol]:
            del self.held[leg.symbol]
        self.orders[cid] = OrderInfo(
            cid,
            "filled" if qty == spec.qty else "partially_filled",
            qty,
            price,
            self.clock.now().strftime("%Y-%m-%d %H:%M:%S"),
            [LegFill(leg.symbol, leg.side, qty, price)],
        )

    def _update(self):
        for cid, spec in self.specs.items():
            if self.orders[cid].final:
                continue
            tag = self.tag(cid)
            fills = self.entry_fills if tag == "entry" else self.stop_fills.get(tag, [])
            for at, qty, price in fills:
                if self.clock.now() >= at and qty > self.orders[cid].filled_qty:
                    self._fill(cid, qty, price)
            if tag in ("moc", "latex") and self.close_fills:
                if tag == "latex" or self.clock.now() >= ts(self.calendar[1]):
                    self._fill(cid, spec.qty, 102.0)
            if cid in self.cancel_at and self.clock.now() >= self.cancel_at[cid]:
                if not self.orders[cid].final:
                    self.orders[cid].status = "canceled"

    def order(self, cid):
        self._update()
        return self.orders.get(cid)

    def submit(self, spec):
        assert spec.client_id not in self.orders, "duplicate submission"
        self.sent.append(spec)
        self.specs[spec.client_id] = spec
        self.orders[spec.client_id] = OrderInfo(
            spec.client_id,
            "rejected" if self.tag(spec.client_id) in self.reject else "accepted",
            0,
            None,
            None,
        )
        return self.order(spec.client_id)

    def cancel(self, cid):
        self.cancelled.append((cid, self.clock.now()))
        if not self.orders[cid].final:
            self.cancel_at[cid] = self.clock.now() + pd.Timedelta(seconds=self.cancel_delay)
        self._update()


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    # Any accidental default client or signal connection fails before touching a socket.
    monkeypatch.setattr(OA, "AlpacaPaper", Mock(side_effect=AssertionError("network client")))
    monkeypatch.setattr(OA, "plan_day", Mock(side_effect=AssertionError("live signal")))


def go(tmp_path, api=None, clock=None, plan=PLAN, plan_fn=None):
    clock = clock or FakeClock()
    api = api or FakeAlpaca(clock)
    OA.run(api=api, clock=clock, root=tmp_path, plan_fn=plan_fn or (lambda *args: plan))
    return api, Ledger.load(OA.LEDGER, OA.STARTING_CASH, tmp_path)


def day_log(tmp_path):
    path = Ledger.directory(OA.LEDGER, tmp_path) / "days" / f"{DAY}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def equity(tmp_path):
    return pd.read_csv(Ledger.directory(OA.LEDGER, tmp_path) / "equity.csv")


@pytest.mark.parametrize(
    "stop,limit,cls",
    [
        (100, 100, StopLimitOrderRequest),
        (98, None, StopOrderRequest),
        (None, None, MarketOrderRequest),
        (None, 100, LimitOrderRequest),
    ],
)
def test_order_request(stop, limit, cls):
    request = order_request(OrderSpec("test", (Leg("AAA", "sell"),), 10, limit, stop=stop))
    assert isinstance(request, cls)
    assert request.qty == 10 and request.symbol == "AAA" and request.side.value == "sell"
    assert request.client_order_id == "test" and request.time_in_force.value == "day"
    if stop is not None:
        assert request.stop_price == stop
    if limit is not None:
        assert request.limit_price == limit


def test_mleg_with_stop_is_rejected():
    legs = (Leg("A", "buy", "buy_to_open"), Leg("B", "sell", "sell_to_open"))
    with pytest.raises(ValueError, match="multi-leg.*stop"):
        order_request(OrderSpec("test", legs, 1, 2.0, stop=2.0))
    request = order_request(OrderSpec("test", legs, 1, 2.0))
    assert isinstance(request, LimitOrderRequest) and request.order_class.value == "mleg"


@pytest.mark.parametrize("status", ["accepted", *sorted(FINAL), "missing"])
def test_adapter_cancel_uses_alpaca_id_only_for_working_orders(status):
    api = object.__new__(AlpacaPaper)
    api.trading = Mock()
    if status == "missing":
        api.trading.get_order_by_client_id.side_effect = APIError('{"message":"not found"}')
    else:
        api.trading.get_order_by_client_id.return_value = SimpleNamespace(status=status, id="uuid")
    api.cancel("our-id")
    api.trading.get_order_by_client_id.assert_called_once_with("our-id")
    if status == "accepted":
        api.trading.cancel_order_by_id.assert_called_once_with("uuid")
    else:
        api.trading.cancel_order_by_id.assert_not_called()


def test_adapter_cancel_propagates_api_failure():
    api = object.__new__(AlpacaPaper)
    api.trading = Mock()
    api.trading.get_order_by_client_id.side_effect = APIError('{"message":"unauthorized"}')
    with pytest.raises(APIError):
        api.cancel("our-id")


@pytest.mark.parametrize("side", [1, -1])
def test_happy_path_stop_then_moc_and_zero_commission(tmp_path, caplog, side):
    plan = replace(PLAN, side=side, stop_px=100 - 2 * side)
    with caplog.at_level("INFO"):
        api, ledger = go(tmp_path, plan=plan)
    entry, stop, moc = api.sent
    assert entry.client_id == f"orba-{DAY}-entry"
    assert entry.stop == entry.limit == PLAN.level and entry.tif == "day"
    assert stop.client_id == f"orba-{DAY}-stop1"
    assert stop.legs[0].side == ("sell" if side > 0 else "buy")
    assert stop.stop == plan.stop_px and stop.limit is None and stop.qty == 10
    assert api.cancelled == [(stop.client_id, ts("15:44:00"))]
    assert moc.client_id == f"orba-{DAY}-moc" and moc.tif == "cls" and moc.qty == 10
    assert ledger.holdings == api.positions() == {}
    assert ledger.cash == 5000 + 10 * 2 * side
    fills = ledger.fills()
    assert list(fills.exec_id) == [entry.client_id, moc.client_id]  # canceled stop has no fill
    assert (fills.commission == 0).all() and (fills.modeled_commission > 0).all()
    assert fills.iloc[0].ref_price == PLAN.level and math.isnan(fills.iloc[1].ref_price)
    assert set(fills.source) == {"alpaca"}
    assert equity(tmp_path).equity.tolist() == [ledger.cash]
    assert len(day_log(tmp_path)["statuses"]) == 3
    events = (Ledger.directory(OA.LEDGER, tmp_path) / "events.jsonl").read_text().splitlines()
    assert {json.loads(row)["kind"] for row in events} >= {
        "start",
        "plan",
        "order",
        "fill",
        "decision",
    }
    assert "entry filled 10 @ 100" in caplog.text and "sent MOC for 10" in caplog.text
    assert f"{OA.LEDGER}: equity $" in caplog.text


@pytest.mark.parametrize("side", [1, -1])
def test_stop_out_cancels_entry_and_sends_no_moc(tmp_path, caplog, side):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    plan = replace(PLAN, side=side, stop_px=100 - 2 * side)
    api.entry_fills = [(ts("15:43:52"), 4, 100)]  # remainder still working when stopped
    api.stop_fills["stop1"] = [(ts("15:43:54"), 4, plan.stop_px)]
    with caplog.at_level("INFO"):
        api, ledger = go(tmp_path, api, clock, plan)
    assert [api.tag(s.client_id) for s in api.sent] == ["entry", "stop1"]
    assert api.orders[f"orba-{DAY}-entry"].status == "canceled"
    assert ledger.holdings == {} and len(ledger.fills()) == 2
    assert ledger.cash == 5000 + 4 * (plan.stop_px - plan.level) * side
    fills = ledger.fills().set_index("exec_id")
    assert fills.loc[f"orba-{DAY}-stop1", "ref_price"] == plan.stop_px
    assert "stopped out 4 @" in caplog.text


def test_no_fill_cancels_at_cutoff_and_records_unchanged_equity(tmp_path, caplog):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.entry_fills = []
    with caplog.at_level("INFO"):
        api, ledger = go(tmp_path, api, clock)
    assert len(api.sent) == 1 and ledger.fills().empty
    assert api.cancelled == [(f"orba-{DAY}-entry", ts("15:44:00"))]
    assert equity(tmp_path).equity.tolist() == [5000]
    assert day_log(tmp_path)["decision"] == "no fill by 15:44; entry cancelled"
    assert "no fill by 15:44; entry cancelled" in caplog.text


@pytest.mark.parametrize("flag", ["shortable", "easy_to_borrow"])
def test_short_requires_both_borrow_flags(tmp_path, flag):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.flags[flag] = False
    go(tmp_path, api, clock, replace(PLAN, side=-1))
    assert api.sent == []
    assert day_log(tmp_path)["decision"] == "not shortable at Alpaca"
    assert equity(tmp_path).equity.tolist() == [5000]


def test_kill_switch_before_entry_raises(tmp_path):
    path = kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("on")
    clock = FakeClock()
    api = FakeAlpaca(clock)
    with pytest.raises(GuardError, match="kill switch"):
        go(tmp_path, api, clock)
    assert api.sent == []


def test_kill_switch_after_partial_entry_still_protects_and_closes(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.entry_fills = [(ts("15:43:52"), 4, 100), (ts("15:43:56"), 10, 100)]

    def kill():
        if clock.now() >= ts("15:43:54"):
            path = kill_switch_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("on")

    clock.hook = kill
    api, ledger = go(tmp_path, api, clock)
    assert [s.qty for s in api.sent] == [10, 4, 4]
    assert api.cancelled[0] == (f"orba-{DAY}-entry", ts("15:43:54"))
    assert ledger.holdings == {} and ledger.cash == 5008


def test_rerun_same_day_does_not_replan_resend_or_book_twice(tmp_path):
    clock = FakeClock()
    api, first = go(tmp_path, clock=clock)
    planner = Mock(side_effect=AssertionError("replanned"))
    _, second = go(tmp_path, api, clock, plan_fn=planner)
    assert len(api.sent) == 3 and len(second.fills()) == 2
    assert second.cash == first.cash and second.holdings == {}
    assert len(second.seen_exec_ids) == len(set(second.seen_exec_ids)) == 2
    assert len(equity(tmp_path)) == 1
    planner.assert_not_called()


@pytest.mark.parametrize("partial", [False, True])
def test_restart_after_crash_with_working_stop_recovers_fills(tmp_path, partial):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    if partial:
        api.entry_fills = [(ts("15:43:52"), 4, 100), (ts("15:43:56"), 10, 100)]

    def crash():
        if clock.now() >= ts("15:43:54"):
            raise RuntimeError("crash")

    clock.hook = crash
    with pytest.raises(RuntimeError, match="crash"):
        go(tmp_path, api, clock)
    clock.hook = None
    planner = Mock(side_effect=AssertionError("replanned"))
    _, ledger = go(tmp_path, api, clock, plan_fn=planner)
    assert sum(api.tag(s.client_id) == "entry" for s in api.sent) == 1
    assert len(ledger.fills()) == 2 and ledger.holdings == {} and ledger.cash == 5020
    assert len(api.sent) == (4 if partial else 3)
    planner.assert_not_called()


def test_partial_entry_then_more_fills_replaces_stop_for_total(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.entry_fills = [(ts("15:43:52"), 4, 100), (ts("15:43:56"), 10, 100)]
    api, ledger = go(tmp_path, api, clock)
    assert [(api.tag(s.client_id), s.qty) for s in api.sent] == [
        ("entry", 10),
        ("stop1", 4),
        ("stop2", 10),
        ("moc", 10),
    ]
    assert api.cancelled == [
        (f"orba-{DAY}-stop1", ts("15:43:56")),
        (f"orba-{DAY}-stop2", ts("15:44:00")),
    ]
    assert len(ledger.fills()) == 2 and ledger.cash == 5020


def test_stop_fill_during_cancel_reduces_moc_and_books_all_three_fills_once(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.cancel_delay = 4
    api.stop_fills["stop1"] = [(ts("15:44:02"), 3, 98)]
    api, ledger = go(tmp_path, api, clock)
    assert api.sent[-1].qty == 7 and api.sent[-1].tif == "cls"
    assert ledger.holdings == {} and ledger.cash == 5008
    fills = ledger.fills()
    assert len(fills) == 3 and fills.quantity.tolist() == [10, -3, -7]
    go(tmp_path, api, clock)
    assert len(Ledger.load(OA.LEDGER, 5000, tmp_path).fills()) == 3


def test_entry_fills_during_cutoff_cancellation_is_closed(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.cancel_delay = 4
    api.entry_fills = [(ts("15:44:02"), 10, 100)]
    api, ledger = go(tmp_path, api, clock)
    assert [(api.tag(s.client_id), s.qty) for s in api.sent] == [("entry", 10), ("moc", 10)]
    assert ledger.holdings == {} and ledger.cash == 5020


def test_account_pin_mismatch_raises(tmp_path):
    clock = FakeClock()
    api, _ = go(tmp_path, clock=clock, plan=None)
    api.account_id = "PA-other"
    with pytest.raises(GuardError, match="not PA9"):
        go(tmp_path, api, clock)
    assert api.sent == []


def test_overnight_position_on_new_day_raises(tmp_path):
    ledger = Ledger(OA.LEDGER, 4900, holdings={"AAA": 1}, root=tmp_path)
    ledger.save()
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.held = {"AAA": 1}
    with pytest.raises(GuardError, match="flat.*new day"):
        go(tmp_path, api, clock)
    assert api.sent == []


def test_unexplained_account_position_fails_reconcile(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.held = {"OTHER": 1}
    with pytest.raises(GuardError, match="reconcile"):
        go(tmp_path, api, clock)
    assert api.sent == []


def test_half_day_uses_earlier_cutoff_and_moc(tmp_path):
    clock = FakeClock("12:43:50")
    api = FakeAlpaca(clock)
    api.calendar = ("09:30", "13:00")
    api, ledger = go(tmp_path, api, clock)
    assert api.sent[-1].tif == "cls"
    assert api.cancelled == [(f"orba-{DAY}-stop1", ts("12:44:00"))]
    assert clock.now() == ts("13:02:00") and ledger.holdings == {}


def seed_entry(tmp_path, api, clock):
    path = Ledger.directory(OA.LEDGER, tmp_path) / "days" / f"{DAY}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plan": asdict(PLAN)}))
    api.submit(OrderSpec(f"orba-{DAY}-entry", (Leg("AAA", "buy"),), 10, 100, stop=100))


def test_late_restart_uses_day_market_instead_of_moc(tmp_path):
    clock = FakeClock("15:51:00")
    api = FakeAlpaca(clock)
    api.entry_fills = [(ts("15:40:00"), 10, 100)]
    seed_entry(tmp_path, api, clock)
    api, ledger = go(tmp_path, api, clock)
    assert api.sent[-1].client_id == f"orba-{DAY}-latex" and api.sent[-1].tif == "day"
    assert ledger.holdings == {} and len(ledger.fills()) == 2


def test_recovery_books_final_unbooked_entry_and_moc_without_resending(tmp_path):
    clock = FakeClock("16:03:00")
    api = FakeAlpaca(clock)
    api.entry_fills = [(ts("15:40:00"), 10, 100)]
    seed_entry(tmp_path, api, clock)
    api.submit(OrderSpec(f"orba-{DAY}-moc", (Leg("AAA", "sell"),), 10, None, "cls"))
    _, ledger = go(tmp_path, api, clock)
    assert len(api.sent) == len(ledger.fills()) == 2
    assert ledger.cash == 5020 and ledger.holdings == {}


def test_closed_session_logs_skip_without_account_or_planner(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.calendar = None
    api.account = Mock(side_effect=AssertionError("account on closed day"))
    go(tmp_path, api, clock)
    assert api.sent == []
    events = (Ledger.directory(OA.LEDGER, tmp_path) / "events.jsonl").read_text()
    assert json.loads(events)["kind"] == "skip"


def test_no_candidate_saves_reason_and_equity(tmp_path):
    def no_plan(day, equity, day_log):
        assert str(day) == DAY and equity == 5000
        day_log["decision"] = "no candidate"
        return None

    api, ledger = go(tmp_path, plan_fn=no_plan)
    assert api.sent == [] and ledger.fills().empty
    assert day_log(tmp_path)["decision"] == "no candidate"
    assert equity(tmp_path).equity.tolist() == [5000]


@pytest.mark.parametrize("qty,reason", [(203, "leverage cap"), (1, "rejected")])
def test_entry_rejection_and_leverage_guard(tmp_path, qty, reason):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.reject.add("entry")
    with pytest.raises(GuardError, match=reason):
        go(tmp_path, api, clock, replace(PLAN, qty=qty))
    assert len(api.sent) == (0 if qty == 203 else 1)


def test_untradable_asset_records_decision(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.flags["tradable"] = False
    go(tmp_path, api, clock)
    assert api.sent == [] and day_log(tmp_path)["decision"] == "not tradable at Alpaca"


def test_new_entry_after_cutoff_is_skipped(tmp_path):
    api, _ = go(tmp_path, clock=FakeClock("15:44:00"))
    assert api.sent == [] and day_log(tmp_path)["decision"] == "entry cutoff passed"


def test_unconfirmed_stop_cancel_never_sends_overlapping_exit(tmp_path):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.cancel_delay = 120
    with pytest.raises(GuardError, match="cancellation not final"):
        go(tmp_path, api, clock)
    assert [api.tag(s.client_id) for s in api.sent] == ["entry", "stop1"]


def test_unfilled_closing_order_times_out_and_reports_not_flat(tmp_path, caplog):
    clock = FakeClock()
    api = FakeAlpaca(clock)
    api.close_fills = False
    _, ledger = go(tmp_path, api, clock)
    assert "not flat after the close" in caplog.text
    assert ledger.holdings == {"AAA": 10}
    assert day_log(tmp_path)["decision"] == "not flat after the close"
    assert not (Ledger.directory(OA.LEDGER, tmp_path) / "equity.csv").exists()
    assert clock.now() <= ts("16:12:00")


def test_default_plan_uses_shared_signal_and_disconnects(monkeypatch):
    from horizon_trader.execution import ibkr

    ib = Mock()
    connect = Mock(return_value=ib)
    monkeypatch.setattr(ibkr, "connect", connect)
    feats, day_log = object(), {}
    monkeypatch.setattr(OA.orb_live, "history", Mock(return_value=feats))
    scan = Mock(return_value=(PLAN, object()))
    monkeypatch.setattr(OA.orb_live, "scan_and_plan", scan)
    assert default_plan_day(pd.Timestamp(DAY).date(), 5000, day_log) == PLAN
    connect.assert_called_once_with(readonly=True, client_id=22)
    scan.assert_called_once_with(ib, pd.Timestamp(DAY).date(), feats, 5000, day_log)
    ib.disconnect.assert_called_once()
    ib.disconnect.reset_mock()
    scan.side_effect = RuntimeError("bad scan")
    with pytest.raises(RuntimeError, match="bad scan"):
        default_plan_day(pd.Timestamp(DAY).date(), 5000, day_log)
    ib.disconnect.assert_called_once()


# --- plan_day: follow the IBKR runner's decision ------------------------------------------


class _Clock:
    def __init__(self, start):
        self.t = pd.Timestamp(start, tz="America/New_York")

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += pd.Timedelta(seconds=max(seconds, 0))


def _ibkr_log(root, day, payload):
    path = root / "orb" / "days" / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


IBKR_PLAN = {"ticker": "ABC", "side": 1, "level": 20.0, "stop_px": 19.5, "qty": 100,
             "atr": 0.5, "relvol": 25.0, "equity": 5000.0}  # fmt: skip


def test_plan_day_resizes_the_ibkr_pick_for_this_ledger(tmp_path):
    day = date(2026, 11, 9)
    _ibkr_log(tmp_path, day, {"plan": IBKR_PLAN, "decision": "placed"})
    log = {}
    plan = default_plan_day(day, 2500.0, log, _Clock("2026-11-09 09:36"), tmp_path)
    assert (plan.ticker, plan.side, plan.level, plan.stop_px) == ("ABC", 1, 20.0, 19.5)
    assert plan.qty == 50  # 1% of $2,500 at risk over a $0.50 stop (orb_live.plan_trade)
    assert log["source"] == "ibkr runner"


def test_plan_day_follows_an_ibkr_no_trade_decision(tmp_path):
    day = date(2026, 11, 9)
    _ibkr_log(tmp_path, day, {"decision": "no candidate"})
    log = {}
    assert default_plan_day(day, 5000.0, log, _Clock("2026-11-09 09:36"), tmp_path) is None
    assert log["decision"] == "IBKR runner: no candidate"


def test_plan_day_waits_then_scans_itself_after_the_deadline(tmp_path, monkeypatch):
    day = date(2026, 11, 9)
    calls = []
    monkeypatch.setattr(OA.orb_live, "history", lambda d: "feats")

    class FakeIB:
        def disconnect(self):
            calls.append("disconnect")

    import horizon_trader.execution.ibkr as ibkr_mod

    monkeypatch.setattr(ibkr_mod, "connect", lambda readonly, client_id: FakeIB())

    def scan(ib, d, feats, equity, log):
        calls.append(("scan", d, feats, equity))
        return None, None

    monkeypatch.setattr(OA.orb_live, "scan_and_plan", scan)
    clock = _Clock("2026-11-09 09:35")
    log = {}
    assert default_plan_day(day, 5000.0, log, clock, tmp_path) is None
    assert clock.now() >= pd.Timestamp("2026-11-09 09:38", tz="America/New_York")
    assert calls == [("scan", day, "feats", 5000.0), "disconnect"]
    assert log["source"] == "own scan"
