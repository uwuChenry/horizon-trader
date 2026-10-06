"""Ledger, shadow fills and the IBKR paper adapter, against a fake ib_async connection."""

from types import SimpleNamespace

import pandas as pd
import pytest
from ib_async import CommissionReport, Execution, OrderState

from horizon_trader.config import LiveSettings
from horizon_trader.execution import Order
from horizon_trader.execution.costs import ibkr_costs
from horizon_trader.execution.ibkr_broker import (
    GuardError,
    IBKRBroker,
    paper_account,
    reconcile,
)
from horizon_trader.execution.ledger import Ledger, fill_pending_at_open
from horizon_trader.run_daily import market_open, run

COSTS = ibkr_costs("tiered", slippage_bps=5)
AFTER_CLOSE = pd.Timestamp("2026-01-09 17:00", tz="America/New_York")

STATIC_CONFIG = """
universe: [SPY, IEF]
sleeves:
  core: {type: static, allocation: 0.9, params: {weights: {SPY: 0.6, IEF: 0.4}}}
risk: {max_weight: 0.6, max_gross: 1.0}
"""


class FakeIB:
    """Just enough of ib_async.IB: orders rest until `fill_open` fills them like an OPG order."""

    def __init__(self, account="DU123", commission=0.42):
        self.accounts = [account] if isinstance(account, str) else account
        self.commission = commission
        self.trades, self._fills, self.held, self.what_if_calls = [], [], {}, 0
        self.cancelled = False
        self.reject: set[str] = set()

    def managedAccounts(self):
        return self.accounts

    def openTrades(self):
        return list(self.trades)

    def placeOrder(self, contract, order):
        status = "Inactive" if contract.symbol in self.reject else "PreSubmitted"
        trade = SimpleNamespace(
            contract=contract, order=order, orderStatus=SimpleNamespace(status=status), log=[]
        )
        self.trades.append(trade)
        return trade

    def whatIfOrder(self, contract, order):
        self.what_if_calls += 1
        return OrderState(commission=1.0, initMarginChange="0")

    def reqExecutions(self, execFilter=None):
        return self.fills()

    def sleep(self, seconds):
        pass

    def fills(self):
        return list(self._fills)

    def positions(self, account=""):
        return [
            SimpleNamespace(contract=SimpleNamespace(symbol=s), position=q)
            for s, q in self.held.items()
        ]

    def reqGlobalCancel(self):
        self.cancelled, self.trades = True, []

    def fill_open(self, opens: dict[str, float], when: str):
        for i, t in enumerate(self.trades):
            sign = 1 if t.order.action == "BUY" else -1
            exec_id = f"{when}-{len(self._fills)}-{i}"
            ex = Execution(
                execId=exec_id, time=pd.Timestamp(when, tz="UTC").to_pydatetime(),
                side="BOT" if sign > 0 else "SLD", shares=t.order.totalQuantity,
                price=opens[t.contract.symbol], orderRef=t.order.orderRef,
            )  # fmt: skip
            report = CommissionReport(execId=exec_id, commission=self.commission)
            self._fills.append(SimpleNamespace(contract=t.contract, execution=ex,
                                               commissionReport=report, time=ex.time))  # fmt: skip
            sym = t.contract.symbol
            self.held[sym] = self.held.get(sym, 0.0) + sign * t.order.totalQuantity
        self.trades = []


def make_bars(days: int):
    idx = pd.bdate_range("2026-01-05", periods=days)
    close = pd.DataFrame({"SPY": 100.0 + pd.RangeIndex(days), "IEF": 50.0}, index=idx)
    return lambda symbols: {"open": close - 0.5, "close": close}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(STATIC_CONFIG)
    return path


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path / "data"))  # kill switch lives here


# -- ledger -------------------------------------------------------------------------------
def test_ledger_books_fills_and_round_trips(tmp_path):
    led = Ledger.load("t", 5000, root=tmp_path)
    led.apply_fill(time="t", source="x", symbol="SPY", quantity=10, price=100.0,
                   commission=0.5, modeled_commission=0.4, exec_id="e1")  # fmt: skip
    assert led.cash == pytest.approx(5000 - 1000 - 0.5)
    assert led.equity({"SPY": 110.0}) == pytest.approx(3999.5 + 1100)
    led.record_equity("2026-01-05", {"SPY": 110.0})
    led.record_equity("2026-01-05", {"SPY": 120.0})  # same date replaces the row
    led.save()

    again = Ledger.load("t", 5000, root=tmp_path)
    assert again.holdings == {"SPY": 10} and again.seen_exec_ids == ["e1"]
    eq = pd.read_csv(Ledger.directory("t", tmp_path) / "equity.csv")
    assert len(eq) == 1 and eq["equity"].iloc[0] == pytest.approx(3999.5 + 1200)
    assert again.fills()["commission"].tolist() == [0.5]


def test_shadow_fills_at_next_open_with_costs(tmp_path):
    led = Ledger.load("s", 5000, root=tmp_path)
    led.add_pending([Order("SPY", 10)], {"SPY": 100.0}, "2026-01-05")
    opens = pd.DataFrame({"SPY": [99.0, 101.0]}, index=pd.to_datetime(["2026-01-05", "2026-01-06"]))
    assert fill_pending_at_open(led, opens.iloc[:1], COSTS) == 0  # next open not known yet
    assert len(led.pending) == 1
    assert fill_pending_at_open(led, opens, COSTS) == 1
    price = COSTS.fill_price(10, 101.0)
    assert led.holdings == {"SPY": 10} and not led.pending
    assert led.cash == pytest.approx(5000 - 10 * price - COSTS.total(10, price))


# -- guards -------------------------------------------------------------------------------
@pytest.mark.parametrize("accounts", ["U999", ["DU1", "DU2"]])
def test_refuses_live_or_ambiguous_accounts(accounts):
    with pytest.raises(GuardError):
        paper_account(FakeIB(accounts))


def test_caps_are_all_or_nothing(tmp_path):
    ib = FakeIB()
    broker = IBKRBroker(ib, Ledger.load("b", 5000, root=tmp_path),
                        LiveSettings(max_order_value=1000), transmit=True)  # fmt: skip
    orders = [Order("IEF", 5), Order("SPY", 20)]  # $250 is fine, $2,000 is over the cap
    with pytest.raises(GuardError, match="SPY"):
        broker.submit_all(orders, {"IEF": 50.0, "SPY": 100.0}, "2026-01-05")
    assert ib.trades == []

    small = LiveSettings(max_orders_per_day=1)
    broker = IBKRBroker(ib, Ledger.load("b", 5000, root=tmp_path), small, transmit=True)
    with pytest.raises(GuardError, match="cap"):
        broker.submit_all([Order("IEF", 1), Order("IEF", 2)], {"IEF": 50.0}, "2026-01-05")
    assert ib.trades == []


def test_kill_switch_blocks_orders(tmp_path):
    ib = FakeIB()
    switch = tmp_path / "KILL"
    switch.write_text("on")
    broker = IBKRBroker(ib, Ledger.load("k", 5000, root=tmp_path), LiveSettings(),
                        transmit=True, kill_switch=switch)  # fmt: skip
    with pytest.raises(GuardError, match="kill"):
        broker.submit_all([Order("IEF", 1)], {"IEF": 50.0}, "2026-01-05")
    assert ib.trades == []


def test_reconcile_flags_any_gap(tmp_path):
    ib = FakeIB()
    led = Ledger.load("r", 5000, root=tmp_path)
    led.holdings = {"SPY": 3.0}
    ib.held = {"SPY": 3.0}
    reconcile(ib, "DU123", [led])
    ib.held = {"SPY": 3.0, "AAPL": 1.0}  # e.g. a manual trade in the paper account
    with pytest.raises(GuardError, match="AAPL"):
        reconcile(ib, "DU123", [led])


def test_market_hours_guard(config, tmp_path):
    assert market_open(pd.Timestamp("2026-01-09 11:00", tz="America/New_York"))
    assert not market_open(pd.Timestamp("2026-01-10 11:00", tz="America/New_York"))  # Saturday
    assert not market_open(pd.Timestamp("2026-01-09 08:00", tz="America/New_York"))
    with pytest.raises(SystemExit, match="market is open"):
        run(config, "shadow", make_bars(5), root=tmp_path,
            now=pd.Timestamp("2026-01-09 11:00", tz="America/New_York"))  # fmt: skip


# -- end to end ---------------------------------------------------------------------------
def test_dry_run_end_to_end_without_network(config):
    targets, orders = run(config, "dry-run", make_bars(5))
    assert targets.abs().sum() == pytest.approx(0.9)
    assert orders and all(o.quantity > 0 for o in orders)  # from all-cash, everything is a buy


def test_there_is_no_live_mode(config):
    with pytest.raises(SystemExit, match="no live mode"):
        run(config, "live", make_bars(5))


def test_shadow_queues_then_fills_at_next_open(config, tmp_path):
    _, orders = run(config, "shadow", make_bars(5), root=tmp_path, now=AFTER_CLOSE)
    assert orders
    _, again = run(config, "shadow", make_bars(5), root=tmp_path, now=AFTER_CLOSE)
    assert again == []  # same signal date: nothing queued twice

    bars = make_bars(6)
    run(config, "shadow", bars, root=tmp_path, now=AFTER_CLOSE)
    fills = Ledger.load("daily_book_shadow", 5000, root=tmp_path).fills()
    assert len(fills) == len(orders)
    next_open = bars([])["open"].iloc[-1]  # day 6, the open after the day-5 signal
    assert (fills["open_price"] == fills["symbol"].map(next_open)).all()
    assert fills["time"].str.startswith("2026-01-12").all()


def test_what_if_places_nothing_and_keeps_no_state(config, tmp_path):
    ib = FakeIB()
    _, orders = run(config, "what-if", make_bars(5), ib=ib, root=tmp_path, now=AFTER_CLOSE)
    assert orders and ib.what_if_calls == len(orders) and ib.trades == []
    assert not Ledger.directory("daily_book", tmp_path).exists()


def test_paper_round_trip(config, tmp_path):
    ib = FakeIB()
    _, orders = run(config, "paper", make_bars(5), ib=ib, root=tmp_path, now=AFTER_CLOSE)
    assert len(ib.trades) == len(orders) > 0
    assert all(t.order.tif == "OPG" and t.order.orderRef == "daily_book" for t in ib.trades)
    assert all(t.order.account == "DU123" for t in ib.trades)

    _, again = run(config, "paper", make_bars(5), ib=ib, root=tmp_path, now=AFTER_CLOSE)
    assert again == [] and len(ib.trades) == len(orders)  # no duplicates on a re-run

    bars = make_bars(6)
    opens = bars([])["open"].iloc[-1].to_dict()
    ib.fill_open(opens, "2026-01-12 14:30")  # 09:30 New York
    run(config, "paper", bars, ib=ib, root=tmp_path, now=AFTER_CLOSE)  # syncs, reconciles

    led = Ledger.load("daily_book", 5000, root=tmp_path)
    assert led.holdings == pytest.approx(ib.held)
    fills = led.fills()
    assert len(fills) == len(orders)
    assert (fills["commission"] == 0.42).all()  # IBKR's number, not the model's
    assert fills["modeled_commission"].gt(0).all()
    assert (fills["price"] == fills["open_price"]).all()
    assert fills["ref_price"].notna().all()
    assert not led.pending

    run(config, "paper", bars, ib=ib, root=tmp_path, now=AFTER_CLOSE)
    assert len(Ledger.load("daily_book", 5000, root=tmp_path).fills()) == len(orders)  # no rebook


def test_rejected_orders_stop_the_run_and_are_not_pending(tmp_path):
    ib = FakeIB()
    ib.reject = {"SPY"}  # e.g. Gateway in Read-Only API mode, or no permissions
    led = Ledger.load("x", 5000, root=tmp_path)
    broker = IBKRBroker(ib, led, LiveSettings(), transmit=True)
    with pytest.raises(GuardError, match="rejected 1 of 2"):
        broker.submit_all([Order("IEF", 5), Order("SPY", 5)], {"IEF": 50.0, "SPY": 100.0}, "d")
    assert [p.symbol for p in led.pending] == ["IEF"]


def test_what_if_timeout_is_a_clear_error(tmp_path):
    ib = FakeIB()

    def no_answer(contract, order):
        raise TimeoutError

    ib.whatIfOrder = no_answer
    broker = IBKRBroker(ib, Ledger.load("w", 5000, root=tmp_path), LiveSettings(), transmit=False)
    with pytest.raises(GuardError, match="Read-Only API"):
        broker.submit_all([Order("IEF", 1)], {"IEF": 50.0}, "d")
