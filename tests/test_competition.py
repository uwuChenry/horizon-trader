"""The AI competition follower against a fake Alpaca: sizing, order shapes, closes, guards."""

import json
from datetime import datetime

import pytest

from horizon_trader.agents import competition as C
from horizon_trader.execution.alpaca_broker import NY, LegFill, OrderInfo

DAY = "2026-11-05"
AT = datetime(2026, 11, 5, 15, 45, tzinfo=NY)
CALL, SHORT = "SPY261218C00770000", "SPY261218C00785000"


class FakeAlpaca:
    """Fills every order instantly at its limit (or the quote) unless told otherwise."""

    def __init__(self, equity=5_000.0, fill=True, is_open=True, level=3):
        self.acct = {"account": "PA1", "status": "ACTIVE", "equity": equity, "cash": equity,
                     "options_level": level}  # fmt: skip
        self.fill, self.open, self.pos, self.orders, self.sent = fill, is_open, {}, {}, []
        self.quotes = {CALL: (2.00, 2.10), SHORT: (0.80, 0.85)}
        self.stock = {"NVDA": (199.9, 200.0)}

    def account(self):
        return dict(self.acct)

    def is_open(self):
        return self.open

    def positions(self):
        return {s: q for s, q in self.pos.items() if abs(q) > 1e-9}

    def option_quotes(self, symbols):
        return {s: self.quotes[s] for s in symbols if s in self.quotes}

    def stock_quote(self, symbol):
        return self.stock[symbol]

    def order(self, cid):
        return self.orders.get(cid)

    def submit(self, spec):
        self.sent.append(spec)
        legs = []
        for lg in spec.legs:
            px = (
                spec.limit
                if len(spec.legs) == 1 and spec.limit
                else (self.quotes.get(lg.symbol, (1, 1))[0 if lg.side == "sell" else 1])
            )
            q = spec.qty if self.fill else 0.0
            legs.append(LegFill(lg.symbol, lg.side, q, px if self.fill else None))
            if self.fill:
                self.pos[lg.symbol] = self.pos.get(lg.symbol, 0) + (q if lg.side == "buy" else -q)
        info = OrderInfo(
            spec.client_id,
            "filled" if self.fill else "new",
            spec.qty if self.fill else 0.0,
            spec.limit,
            f"{DAY} 15:45:01",
            legs,
        )
        self.orders[spec.client_id] = info
        return info

    def expire_all(self):
        for cid, o in self.orders.items():
            if not o.final:
                self.orders[cid] = OrderInfo(cid, "expired", 0.0, None, None, o.legs)

    def cancel_all(self):
        self.expire_all()


def idea(pid="2026-11-05-1", structure="long_call", legs=None, date=DAY, status="open",
         kind="idea", expiry="2026-12-18"):  # fmt: skip
    legs = legs or [{"type": "option", "symbol": CALL, "side": 1, "bid": 2.0, "ask": 2.1,
                     "right": "C", "strike": 770.0, "expiry": expiry}]  # fmt: skip
    return {"id": pid, "kind": kind, "date": date, "underlying": "SPY", "structure": structure,
            "legs": legs, "qty": 1, "expiry": expiry if legs[0]["type"] == "option" else None,
            "status": status, "unit_entry": 2.1}  # fmt: skip


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path / "data"))


def go(broker, positions, root, **kw):
    kw.setdefault("now", AT)
    return C.run(broker, positions, today=kw.pop("today", DAY), root=root, sleep=lambda s: None,
                 **kw)  # fmt: skip


def test_long_call_sized_at_2_5x_journal_budget(tmp_path):
    b = FakeAlpaca()
    s = go(b, [idea()], tmp_path)
    (spec,) = b.sent
    assert spec.limit == 2.10 and spec.qty == 1  # $375 / $210 per contract -> 1
    assert spec.legs[0].intent == "buy_to_open" and spec.client_id == "compai-2026-11-05-1-open"
    assert s["opened"] and C.load_state(tmp_path)["records"]["2026-11-05-1"]["status"] == "opening"
    b.quotes[CALL] = (1.00, 1.05)  # cheaper premium -> more contracts
    go(b, [idea(pid="2026-11-05-2", legs=[{"type": "option", "symbol": CALL, "side": 1,
              "bid": 1.0, "ask": 1.05}])], tmp_path)  # fmt: skip
    assert b.sent[-1].qty == 3  # the $375 cap is per idea: 375 // 105


def test_total_premium_cap(tmp_path):
    b = FakeAlpaca()
    b.quotes[CALL] = (1.00, 1.05)
    ideas = [idea(pid=f"2026-11-05-{i}") for i in range(1, 7)]
    go(b, ideas, tmp_path)
    spent = sum(s.qty * s.limit * 100 for s in b.sent)
    assert spent <= 1_500 and len(b.sent) == 5  # 4 x $315, then $240 left -> 2 x $105


def test_debit_spread_is_one_multileg_limit_at_net_debit(tmp_path):
    legs = [
        {"type": "option", "symbol": CALL, "side": 1, "bid": 2.0, "ask": 2.1},
        {"type": "option", "symbol": SHORT, "side": -1, "bid": 0.8, "ask": 0.85},
    ]
    b = FakeAlpaca()
    go(b, [idea(structure="call_debit_spread", legs=legs)], tmp_path)
    (spec,) = b.sent
    assert [lg.intent for lg in spec.legs] == ["buy_to_open", "sell_to_open"]
    assert spec.limit == pytest.approx(1.30) and spec.qty == 2  # 2.10 - 0.80; $375 // $130


def test_spread_needs_options_level_3(tmp_path):
    legs = [{"type": "option", "symbol": CALL, "side": 1}, {"type": "option", "symbol": SHORT,
            "side": -1}]  # fmt: skip
    b = FakeAlpaca(level=2)
    s = go(b, [idea(structure="call_debit_spread", legs=legs)], tmp_path)
    assert not b.sent and "level 2 < 3" in s["skipped"][0]


def test_shares_idea_buys_fractional_shares_under_cap(tmp_path):
    b = FakeAlpaca()
    stock = idea(structure="shares_long", legs=[{"type": "stock", "symbol": "NVDA", "side": 1}])
    stock["underlying"] = "NVDA"
    go(b, [stock], tmp_path)
    (spec,) = b.sent
    assert spec.limit == round(200.0 * 1.002, 2) and spec.qty == pytest.approx(7.485, abs=1e-3)
    assert spec.legs[0].intent == ""
    b.stock["NVDA"] = (193.24, 209.70)  # a thin pre-market IEX quote seen on the real API
    s = go(b, [stock | {"id": "2026-11-05-2"}], tmp_path)
    assert len(b.sent) == 1 and "IEX quote too wide" in s["skipped"][0]


def test_wide_quote_and_mirror_are_skipped(tmp_path):
    b = FakeAlpaca()
    b.quotes[CALL] = (1.0, 2.0)
    s = go(b, [idea(), idea(pid="2026-11-05-1-m", kind="mirror")], tmp_path)
    assert not b.sent and "too wide" in s["skipped"][0] and len(s["skipped"]) == 1


def test_journal_close_sells_short_leg_first_then_long(tmp_path):
    legs = [
        {"type": "option", "symbol": CALL, "side": 1, "bid": 2.0, "ask": 2.1},
        {"type": "option", "symbol": SHORT, "side": -1, "bid": 0.8, "ask": 0.85},
    ]
    b = FakeAlpaca()
    p = idea(structure="call_debit_spread", legs=legs)
    go(b, [p], tmp_path)
    assert b.positions() == {CALL: 2, SHORT: -2}
    go(b, [p | {"status": "closed", "exit_reason": "horizon"}], tmp_path, today="2026-11-12")
    closes = b.sent[1:]
    assert [(s.legs[0].symbol, s.legs[0].intent, s.limit) for s in closes] == [
        (SHORT, "buy_to_close", None), (CALL, "sell_to_close", None)]  # fmt: skip
    go(b, [p], tmp_path, today="2026-11-13")  # sync books the closes
    rec = C.load_state(tmp_path)["records"][p["id"]]
    assert rec["status"] == "closed" and rec["close_reason"] == "journal (horizon)"
    assert b.positions() == {}


def test_option_closes_the_day_before_expiry_and_everything_at_contest_end(tmp_path):
    b = FakeAlpaca()
    p = idea(expiry="2026-11-20")
    go(b, [p], tmp_path)
    s = go(b, [p], tmp_path, today="2026-11-18")
    assert not s["closed"]
    s = go(b, [p], tmp_path, today="2026-11-19")
    assert s["closed"] == ["2026-11-05-1 (day before expiry)"]
    rec = {"asset": "stock", "expiry": None}
    assert C.close_reason(rec, None, "2026-12-28", C.Rules()) == "contest end"


def test_unfilled_entry_becomes_missed_and_is_not_retried(tmp_path):
    b = FakeAlpaca(fill=False)
    go(b, [idea()], tmp_path)
    b.expire_all()
    s = go(b, [idea()], tmp_path, today="2026-11-06")
    rec = C.load_state(tmp_path)["records"]["2026-11-05-1"]
    assert rec["status"] == "missed" and len(b.sent) == 1 and not s["opened"]


def test_working_orders_block_new_orders(tmp_path):
    b = FakeAlpaca(fill=False)
    go(b, [idea()], tmp_path)
    go(b, [idea(), idea(pid="2026-11-05-2")], tmp_path)  # first order still working
    assert len(b.sent) == 1


def test_position_gap_stops_trading(tmp_path):
    b = FakeAlpaca()
    go(b, [idea()], tmp_path)
    b.pos["TSLA"] = 3  # something we didn't buy
    with pytest.raises(C.GuardError, match="reconcile"):
        go(b, [idea(pid="2026-11-05-2")], tmp_path)


def test_first_run_needs_a_reset_account_and_later_runs_the_same_account(tmp_path):
    with pytest.raises(C.GuardError, match="reset"):
        go(FakeAlpaca(equity=100_000), [idea()], tmp_path)
    b = FakeAlpaca()
    go(b, [], tmp_path)
    b.acct["account"] = "PA2"
    with pytest.raises(C.GuardError, match="not PA1"):
        go(b, [], tmp_path)


def test_kill_switch_and_dry_run(tmp_path):
    b = FakeAlpaca()
    s = go(b, [idea()], tmp_path, dry_run=True)
    assert not b.sent and s["opened"] and not (tmp_path / C.LEDGER).exists()
    C.kill(b)
    with pytest.raises(C.GuardError, match="kill switch"):
        go(b, [idea()], tmp_path)


def test_stale_late_and_closed_market_ideas_are_missed(tmp_path):
    b = FakeAlpaca()
    go(b, [], tmp_path)  # follower starts today
    old = idea(pid="2026-11-05-9")
    s = go(b, [old], tmp_path, today="2026-11-06")
    assert "decision date" in s["missed"][0]
    late = datetime(2026, 11, 6, 15, 58, tzinfo=NY)
    s = go(b, [idea(pid="2026-11-06-1", date="2026-11-06")], tmp_path, today="2026-11-06",
           now=late)  # fmt: skip
    assert "after 15:57" in s["missed"][0] and not b.sent


def test_ledger_files_for_the_dashboard(tmp_path):
    b = FakeAlpaca()
    go(b, [idea()], tmp_path)
    d = tmp_path / C.LEDGER
    assert (d / "equity.csv").exists()
    assert json.loads((d / "state.json").read_text())["holdings"] == {CALL: 1}
    go(b, [idea()], tmp_path, today="2026-11-06")  # sync books the entry fill
    import pandas as pd

    fills = pd.read_csv(d / "fills.csv")
    assert fills.loc[0, "symbol"] == CALL and fills.loc[0, "quantity"] == 100
    assert fills.loc[0, "price"] == 2.10 and fills.loc[0, "ref_price"] == 2.10


def test_tick_rounding():
    assert C.tick_up(1.234, False) == 1.24 and C.tick_up(3.21, False) == 3.25
    assert C.tick_up(3.21, True) == 3.21
