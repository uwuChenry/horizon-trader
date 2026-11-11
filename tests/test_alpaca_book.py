"""run_daily --mode alpaca against a fake Alpaca: fractional orders, fills, reconcile, guards."""

import json

import pandas as pd
import pytest

from horizon_trader.execution.alpaca_book import client_id
from horizon_trader.execution.alpaca_broker import LegFill, OrderInfo
from horizon_trader.execution.ibkr_broker import GuardError
from horizon_trader.execution.ledger import Ledger
from horizon_trader.run_daily import run

AFTER_CLOSE = pd.Timestamp("2026-01-09 17:00", tz="America/New_York")
CONFIG = """
universe: [SPY, IEF]
sleeves:
  core: {type: static, allocation: 0.9, params: {weights: {SPY: 0.6, IEF: 0.4}}}
risk: {max_weight: 0.6, max_gross: 1.0}
"""
LEDGER = "daily_book_alpaca_paper"


class FakeAlpaca:
    """Orders wait ("accepted") until `open_fill` fills them at the given prices."""

    def __init__(self, account="PA1"):
        self.acct, self.orders, self.held, self.sent = account, {}, {}, []
        self.reject: set[str] = set()

    def account(self):
        return {"account": self.acct, "equity": 5000.0, "cash": 5000.0}

    def positions(self):
        return {s: q for s, q in self.held.items() if abs(q) > 1e-9}

    def order(self, cid):
        return self.orders.get(cid)

    def submit(self, spec):
        self.sent.append(spec)
        leg = spec.legs[0]
        status = "rejected" if leg.symbol in self.reject else "accepted"
        info = OrderInfo(spec.client_id, status, 0.0, None, None,
                         [LegFill(leg.symbol, leg.side, 0.0, None)])  # fmt: skip
        self.orders[spec.client_id] = info
        return info

    def open_fill(self, prices, when="2026-01-12 09:30:01", fraction=1.0):
        for cid, o in self.orders.items():
            if o.status != "accepted":
                continue
            spec = next(s for s in self.sent if s.client_id == cid)
            leg = spec.legs[0]
            q = spec.qty * fraction
            self.held[leg.symbol] = self.held.get(leg.symbol, 0) + (q if leg.side == "buy" else -q)
            self.orders[cid] = OrderInfo(cid, "filled" if fraction == 1 else "expired", q,
                                         prices[leg.symbol], when)  # fmt: skip


def bars(days):
    idx = pd.bdate_range("2026-01-05", periods=days)
    close = pd.DataFrame({"SPY": 100.0 + pd.RangeIndex(days), "IEF": 50.0}, index=idx)
    return lambda symbols: {"open": close - 0.5, "close": close}


@pytest.fixture
def config(tmp_path):
    p = tmp_path / "settings.yaml"
    p.write_text(CONFIG)
    return p


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path / "data"))


def go(config, api, root, days=5, now=AFTER_CLOSE):
    return run(config, "alpaca", bars(days), alpaca=api, root=root, now=now)


def test_fractional_orders_for_the_next_open_then_fills_booked(config, tmp_path):
    api = FakeAlpaca()
    _, orders = go(config, api, tmp_path)
    assert {s.legs[0].symbol for s in api.sent} == {"SPY", "IEF"}
    spy = next(s for s in api.sent if s.legs[0].symbol == "SPY")
    assert spy.limit is None and spy.qty != int(spy.qty)  # fractional market order
    assert spy.client_id == client_id(LEDGER, "2026-01-09", "SPY")
    api.open_fill({"SPY": 104.6, "IEF": 49.4})
    go(config, api, tmp_path, days=6, now=AFTER_CLOSE + pd.Timedelta(days=3))
    led = Ledger.load(LEDGER, 5000, tmp_path)
    assert led.holdings["SPY"] == pytest.approx(spy.qty) and not led.pending
    fills = led.fills()
    assert set(fills["source"]) == {"alpaca"} and (fills["commission"] == 0).all()
    row = fills[fills["symbol"] == "SPY"].iloc[0]
    assert row["price"] == 104.6 and row["open_price"] == 104.5  # vs the day's open
    assert row["modeled_commission"] > 0  # what IBKR Tiered would have charged


def test_rerun_same_day_sends_nothing_new(config, tmp_path):
    api = FakeAlpaca()
    go(config, api, tmp_path)
    go(config, api, tmp_path)
    assert len(api.sent) == 2


def test_unfinished_orders_block_planning(config, tmp_path):
    api = FakeAlpaca()
    go(config, api, tmp_path)
    with pytest.raises(GuardError, match="haven't finished"):  # next day, orders not filled yet
        go(config, api, tmp_path, days=6, now=AFTER_CLOSE + pd.Timedelta(days=3))


def test_partial_fill_booked_rest_dropped(config, tmp_path):
    api = FakeAlpaca()
    go(config, api, tmp_path)
    api.open_fill({"SPY": 104.6, "IEF": 49.4}, fraction=0.5)
    go(config, api, tmp_path, days=6, now=AFTER_CLOSE + pd.Timedelta(days=3))
    led = Ledger.load(LEDGER, 5000, tmp_path)
    assert led.holdings["SPY"] == pytest.approx(api.held["SPY"])


def test_reconcile_gap_and_account_pin_stop(config, tmp_path):
    api = FakeAlpaca()
    go(config, api, tmp_path)
    api.open_fill({"SPY": 104.6, "IEF": 49.4})
    api.held["TSLA"] = 1.0
    with pytest.raises(GuardError, match="reconcile"):
        go(config, api, tmp_path, days=6, now=AFTER_CLOSE + pd.Timedelta(days=3))
    with pytest.raises(GuardError, match="not PA1"):
        go(config, FakeAlpaca(account="PA2"), tmp_path)
    pin = json.loads((Ledger.directory(LEDGER, tmp_path) / "alpaca_account.json").read_text())
    assert pin == {"account": "PA1"}


def test_rejection_and_kill_switch(config, tmp_path):
    api = FakeAlpaca()
    api.reject = {"IEF"}
    with pytest.raises(GuardError, match="rejected 1 of 2"):
        go(config, api, tmp_path)
    led = Ledger.load(LEDGER, 5000, tmp_path)
    assert [p.symbol for p in led.pending] == ["SPY"]  # the accepted one is tracked

    from horizon_trader.execution.alpaca_book import kill_switch_path

    kill_switch_path().parent.mkdir(parents=True, exist_ok=True)
    kill_switch_path().write_text("on")
    with pytest.raises(GuardError, match="kill switch"):
        go(config, FakeAlpaca(), tmp_path / "other")


def test_market_hours_refused(config, tmp_path):
    with pytest.raises(SystemExit, match="market is open"):
        go(config, FakeAlpaca(), tmp_path, now=AFTER_CLOSE - pd.Timedelta(hours=6))
