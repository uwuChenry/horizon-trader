"""The AI contest trader against a fake Alpaca, fake chains and a scripted LLM: indicators,
ladders, order checks, mechanical exits, broker stops and the full session loop."""

import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from horizon_trader.agents import contest_prompts as P
from horizon_trader.agents import contest_trader as T
from horizon_trader.agents.competition import GuardError
from horizon_trader.execution.alpaca_broker import NY, LegFill, OrderInfo

DAY = "2026-11-12"
AT = datetime(2026, 11, 12, 13, 30, tzinfo=NY)
EXP = "2026-12-18"
CALL = "AMD261218C00250000"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(T.time, "sleep", lambda s: None)


class FakeAlpaca:
    """Limit/market orders fill at once; stop orders rest until `trigger_stops`."""

    def __init__(self, equity=5_000.0, is_open=True):
        self.acct = {"account": "PA1", "status": "ACTIVE", "equity": equity, "cash": equity,
                     "options_level": 3}  # fmt: skip
        self.open, self.pos, self.orders, self.sent = is_open, {}, {}, []
        self.stock = {"NVDA": (199.9, 200.0), "AMD": (239.9, 240.0)}
        self.opt = {CALL: (9.8, 10.0)}

    def account(self):
        return dict(self.acct)

    def is_open(self):
        return self.open

    def positions(self):
        return {s: q for s, q in self.pos.items() if abs(q) > 1e-9}

    def option_quotes(self, symbols):
        return {s: self.opt[s] for s in symbols if s in self.opt}

    def stock_quote(self, symbol):
        return self.stock[symbol]

    def order(self, cid):
        return self.orders.get(cid)

    def _fill(self, spec, px):
        lg = spec.legs[0]
        self.pos[lg.symbol] = self.pos.get(lg.symbol, 0) + (spec.qty if lg.side == "buy"
                                                            else -spec.qty)  # fmt: skip
        mult = 100 if len(lg.symbol) > 6 else 1
        self.acct["cash"] -= (spec.qty if lg.side == "buy" else -spec.qty) * px * mult
        info = OrderInfo(spec.client_id, "filled", spec.qty, px, f"{DAY} 13:31:00",
                         [LegFill(lg.symbol, lg.side, spec.qty, px)])  # fmt: skip
        self.orders[spec.client_id] = info
        return info

    def submit(self, spec):
        self.sent.append(spec)
        if spec.stop is not None:
            info = OrderInfo(spec.client_id, "new", 0.0, None, None, [])
            self.orders[spec.client_id] = info
            self.specs = getattr(self, "specs", {}) | {spec.client_id: spec}
            return info
        sym = spec.legs[0].symbol
        px = spec.limit or (self.opt.get(sym) or self.stock.get(sym))[0]
        return self._fill(spec, px)

    def trigger_stops(self):
        for cid, spec in getattr(self, "specs", {}).items():
            if not self.orders[cid].final:
                self._fill(spec, spec.stop)

    def cancel(self, cid):
        o = self.orders.get(cid)
        if o and not o.final:
            self.orders[cid] = OrderInfo(cid, "canceled", 0.0, None, None, [])

    def cancel_all(self):
        for cid in list(self.orders):
            self.cancel(cid)


def bars(last=100.0, n=300, drift=0.001):
    idx = pd.bdate_range(end=DAY, periods=n)
    c = last * np.cumprod(np.full(n, 1 + drift)) / np.prod(np.full(n, 1 + drift))
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
                         "Volume": np.full(n, 2e6)}, index=idx)  # fmt: skip


class FakeBars:
    def bars(self, symbols, days=400):
        px = {"NVDA": 200.0, "AMD": 240.0}
        return {s: bars(px.get(s, 100.0)) for s in symbols}

    def earnings_date(self, symbol):
        return "2027-01-28"


def chain_df(spot, right, expiry=EXP):
    ks = np.arange(5 * round(spot * 0.8 / 5), spot * 1.2, 5.0)
    rows = []
    for k in ks:
        sym = f"AMD{expiry[2:].replace('-', '')}{right}{int(k * 1000):08d}"
        intrinsic = max(spot - k, 0) if right == "C" else max(k - spot, 0)
        mid = intrinsic + 6.0
        rows.append({"contractSymbol": sym, "strike": k, "bid": mid - 0.1, "ask": mid + 0.1,
                     "impliedVolatility": 0.5, "openInterest": 500, "lastPrice": mid})  # fmt: skip
    return pd.DataFrame(rows)


class FakeMarket:
    def expiries(self, symbol):
        return ["2026-11-14", "2026-11-27", EXP, "2027-01-15"]

    def chain(self, symbol, expiry):
        return chain_df(240.0, "C", expiry), chain_df(240.0, "P", expiry)


def script(research, decision):
    """A runner returning `research` then `decision`; records the prompts."""
    calls = []

    def runner(prompt, web, schema):
        calls.append({"prompt": prompt, "web": web, "schema": schema})
        out = research if schema is P.RESEARCH_SCHEMA else decision
        return {"structured_output": out, "result": json.dumps(out)}

    runner.calls = calls
    return runner


def cand(t, direction="long", instrument="either"):
    return {"ticker": t, "direction": direction, "instrument": instrument, "horizon_days": 10,
            "catalyst": "c", "catalyst_date": "2026-11-20", "thesis": "t", "why_now": "w",
            "invalidation": "i"}  # fmt: skip


def order(t, instrument="shares", contract="", qty=5, stop=190.0, target=0.0, exit_by="2026-12-04"):
    return {"ticker": t, "instrument": instrument, "contract": contract, "qty": qty, "stop": stop,
            "target": target, "exit_by": exit_by, "expected_move_pct": 8.0, "thesis": "t",
            "catalyst": "c", "invalidation": "i", "confidence": 3}  # fmt: skip


def research(cands=(), reviews=()):
    return {"market_view": "v", "facts": [], "position_reviews": list(reviews),
            "candidates": list(cands), "no_trade_reason": ""}  # fmt: skip


def decision(orders=(), actions=(), notebook="nb", summary="did things"):
    return {"position_actions": list(actions), "orders": list(orders), "notebook": notebook,
            "session_summary": summary}  # fmt: skip


def go(broker, runner, tmp_path, today=DAY, now=AT, **kw):
    return T.run(broker, FakeMarket(), FakeBars(), runner=runner, today=today, now=now,
                 root=tmp_path, journal="", **kw)  # fmt: skip


# ---------------------------------------------------------------- pure pieces


def test_rsi_extremes_and_range():
    up = pd.Series(np.arange(1, 50, dtype=float))
    assert T.rsi(up, 2) == 100.0
    zig = pd.Series([100, 101, 100, 101, 100, 101, 100, 99, 98, 97], dtype=float)
    assert 0 <= T.rsi(zig, 2) < 20


def test_scan_table_columns_and_dollar_volume():
    df = T.scan_table({"A": bars(100.0), "B": bars(50.0, drift=-0.001)})
    assert list(df.index) == ["A", "B"]  # sorted by 20-day return
    assert df.loc["A", "$vol 20d M"] == pytest.approx(200.0, rel=0.05)


def test_ladder_has_breakeven_and_implied_move_and_drops_illiquid():
    m = FakeMarket()
    rows = T.ladder(m, "AMD", "long", DAY, 240.0, T.Rules())
    assert rows and all(r["right"] == "C" and r["expiry"] != "2026-11-14" for r in rows)
    r = rows[0]
    assert r["breakeven"] == pytest.approx(r["strike"] + r["ask"])
    assert r["implied move to expiry %"] == pytest.approx(12.0 / 240 * 100, abs=0.1)

    class Thin(FakeMarket):
        def chain(self, symbol, expiry):
            c, p = super().chain(symbol, expiry)
            return c.assign(openInterest=5), p

    assert T.ladder(Thin(), "AMD", "long", DAY, 240.0, T.Rules()) == []


def ctx(state=None, **kw):
    rows = T.ladder(FakeMarket(), "AMD", "long", DAY, 240.0, T.Rules())
    base = {"today": DAY, "equity": 5_000.0, "cash": 5_000.0,
            "state": state or {"positions": {}}, "ladders": {r["contract"]: r for r in rows},
            "quotes": {"NVDA": (199.9, 200.0), "AMD": (239.9, 240.0)},
            "scan": {"NVDA": {"$vol 20d M": 900.0}, "AMD": {"$vol 20d M": 900.0}},
            "spot": {"NVDA": 199.95, "AMD": 239.95}, "new": 0,
            "candidates": {"NVDA": "long", "AMD": "long"}}  # fmt: skip
    return base | kw


def test_shares_cut_to_the_per_idea_cap():
    pos, note = T.check_order(order("NVDA", qty=100), ctx(), T.Rules())
    assert pos["qty"] == 9 and "cut from 100 to 9" in note  # 40% of $5k at $200.40
    assert pos["stop"] == 190.0 and pos["status"] == "opening"


@pytest.mark.parametrize(
    "o, why",
    [
        (order("TSLA"), "wasn't a step-1 candidate"),
        (order("NVDA", stop=150.0), "within 15%"),
        (order("NVDA", stop=205.0), "must be below"),
        (order("NVDA", target=150.0), "target"),
        (order("NVDA", exit_by=DAY), "isn't after today"),
        (order("AMD", "option", "AMD261218C99999999", qty=1), "isn't in AMD's ladder"),
        (order("AMD", "option", CALL, qty=1, stop=250.0), "wrong side"),
    ],
)
def test_rejections(o, why):
    pos, reason = T.check_order(o, ctx(), T.Rules())
    assert pos is None and why in reason


def test_short_candidate_cannot_buy_shares():
    pos, reason = T.check_order(order("NVDA"), ctx(candidates={"NVDA": "short"}), T.Rules())
    assert pos is None and "use puts" in reason


def test_option_clamped_to_premium_cap_and_exit_before_expiry():
    o = order("AMD", "option", CALL, qty=10, stop=225.0, exit_by="2026-12-24")
    pos, note = T.check_order(o, ctx(), T.Rules())
    assert pos["qty"] == 1  # $1,000 cap / ($6.10 * 100) -> 1
    assert pos["exit_by"] == "2026-12-17" and "exit_by moved" in note
    assert pos["limit"] == 6.10 and pos["cost"] == pytest.approx(610.0)


def test_one_position_per_underlying_and_position_limit():
    held = {"x": {"ticker": "NVDA", "status": "open", "instrument": "shares", "cost": 100.0}}
    pos, reason = T.check_order(order("NVDA"), ctx({"positions": held}), T.Rules())
    assert pos is None and "already holding" in reason
    pos, reason = T.check_order(order("AMD", "option", CALL, qty=1, stop=225.0),
                                ctx({"positions": held}), T.Rules(max_positions=1))  # fmt: skip
    assert pos is None and "positions already open" in reason


def test_mechanical_exits():
    r = T.Rules()
    opt = {"instrument": "option", "expiry": EXP, "exit_by": "2026-12-10", "direction": "long",
           "stop": 225.0, "target": 280.0, "ticker": "AMD"}  # fmt: skip
    assert T.mechanical_exit(opt, DAY, 240.0, r) is None
    assert "stop" in T.mechanical_exit(opt, DAY, 224.0, r)
    assert "target" in T.mechanical_exit(opt, DAY, 281.0, r)
    assert T.mechanical_exit(opt, "2026-12-10", 240.0, r).startswith("exit_by")
    assert T.mechanical_exit(opt | {"exit_by": "2026-12-30"}, "2026-12-17", 240.0, r) == \
        "day before expiry"  # fmt: skip
    assert T.mechanical_exit(opt, "2026-12-28", 240.0, r) == "contest end"
    put = opt | {"direction": "short", "stop": 250.0, "target": 200.0}
    assert "stop" in T.mechanical_exit(put, DAY, 251.0, r)
    shares = opt | {"instrument": "shares", "expiry": None, "target": 0.0}
    assert T.mechanical_exit(shares, DAY, 1.0, r) is None  # shares stops live at the broker


def test_days_left_skips_holidays():
    assert T.trading_days_left("2026-12-21", T.Rules()) == 4  # 21-24 (25th is a holiday anyway)
    assert T.trading_days_left("2026-11-25", T.Rules()) < 23


def test_earnings_never_shows_a_past_date_as_next():
    today = pd.Timestamp(DAY)
    assert (
        T.upcoming([pd.Timestamp("2026-10-29")], today) == "none scheduled (last report 2026-10-29)"
    )
    assert T.upcoming([pd.Timestamp("2026-11-17")], today) == "2026-11-17"
    assert T.upcoming([], today) == "none listed"


def test_prompt_sha_is_stable():
    assert P.prompt_sha() == P.prompt_sha() and len(P.prompt_sha()) == 12


# ---------------------------------------------------------------- full sessions


def test_session_opens_shares_with_broker_stop_and_an_option(tmp_path):
    b = FakeAlpaca()
    run = script(
        research([cand("NVDA", instrument="shares"), cand("AMD", instrument="options")]),
        decision([order("NVDA", qty=5), order("AMD", "option", CALL, qty=1, stop=225.0)]),
    )
    s = go(b, run, tmp_path)
    assert len(s["opened"]) == 2 and not s["rejected"]
    assert run.calls[0]["web"] and not run.calls[1]["web"]
    assert CALL in run.calls[1]["prompt"]  # the ladder reached the decision prompt
    stops = [x for x in b.sent if x.stop is not None]
    assert len(stops) == 1 and stops[0].tif == "gtc" and stops[0].stop == 190.0
    assert stops[0].legs[0].symbol == "NVDA" and stops[0].qty == 5
    st = T.load_state(tmp_path)
    assert st["account"] == "PA1" and st["notebook"] == "nb" and st["start"] == DAY
    assert {p["status"] for p in st["positions"].values()} == {"open"}
    sess = next((T.folder(tmp_path) / "sessions").iterdir())
    for f in (
        "briefing.md",
        "research.prompt.md",
        "decision.raw.json",
        "checks.json",
        "ladders.json",
    ):
        assert (sess / f).exists(), f
    assert (T.folder(tmp_path) / "equity.csv").exists()
    fills = pd.read_csv(T.folder(tmp_path) / "fills.csv")
    assert set(fills["symbol"]) == {"NVDA", CALL}


def test_next_session_closes_on_option_stop_and_books_broker_stop(tmp_path):
    b = FakeAlpaca()
    go(b, script(research([cand("NVDA"), cand("AMD")]),
                 decision([order("NVDA", qty=5), order("AMD", "option", CALL, qty=1, stop=225.0)])),
       tmp_path)  # fmt: skip
    b.trigger_stops()  # NVDA hit 190 overnight
    b.stock["AMD"] = (219.9, 220.0)  # AMD under the option's 225 underlying stop
    run2 = script(research(), decision(notebook="nb2"))
    s = go(b, run2, tmp_path, today="2026-11-13", now=datetime(2026, 11, 13, 13, 30, tzinfo=NY))
    st = T.load_state(tmp_path)
    by = {p["ticker"]: p for p in st["positions"].values()}
    assert by["NVDA"]["status"] == "closed" and by["NVDA"]["close_reason"] == "stop (broker)"
    assert by["NVDA"]["realized"] == pytest.approx(5 * (190.0 - 200.4))
    assert by["AMD"]["status"] == "closed" and by["AMD"]["close_reason"].startswith("stop")
    assert any("AMD" in c for c in s["closed"])
    assert b.positions() == {}
    assert "Track record" in run2.calls[0]["prompt"] and "stop (broker)" in run2.calls[0]["prompt"]


def test_model_close_cancels_the_broker_stop_first(tmp_path):
    b = FakeAlpaca()
    go(b, script(research([cand("NVDA")]), decision([order("NVDA", qty=5)])), tmp_path)
    pid = next(iter(T.load_state(tmp_path)["positions"]))
    act = {"id": pid, "action": "close", "stop": 0, "target": 0, "exit_by": "", "reason": "done"}
    go(b, script(research(), decision(actions=[act])), tmp_path, today="2026-11-13",
       now=datetime(2026, 11, 13, 13, 30, tzinfo=NY))  # fmt: skip
    stop_id = next(x.client_id for x in b.sent if x.stop is not None)
    assert b.orders[stop_id].status == "canceled"
    assert T.load_state(tmp_path)["positions"][pid]["status"] == "closed"
    assert b.positions() == {}


def test_update_moves_the_broker_stop(tmp_path):
    b = FakeAlpaca()
    go(b, script(research([cand("NVDA")]), decision([order("NVDA", qty=5)])), tmp_path)
    pid = next(iter(T.load_state(tmp_path)["positions"]))
    act = {"id": pid, "action": "update", "stop": 195.0, "target": 0, "exit_by": "2026-12-04",
           "reason": "trail"}  # fmt: skip
    go(b, script(research(), decision(actions=[act])), tmp_path, today="2026-11-13",
       now=datetime(2026, 11, 13, 13, 30, tzinfo=NY))  # fmt: skip
    stops = [x for x in b.sent if x.stop is not None]
    assert [x.stop for x in stops] == [190.0, 195.0]
    assert b.orders[stops[0].client_id].status == "canceled"


def test_rejections_are_fed_back_next_session(tmp_path):
    b = FakeAlpaca()
    go(b, script(research([cand("NVDA")]), decision([order("NVDA", stop=100.0)])), tmp_path)
    assert "REJECTED" in T.load_state(tmp_path)["rejected"][0]
    run2 = script(research(), decision())
    go(b, run2, tmp_path, today="2026-11-13", now=datetime(2026, 11, 13, 13, 30, tzinfo=NY))
    assert "within 15%" in run2.calls[0]["prompt"]


def test_market_closed_syncs_without_calling_the_model(tmp_path):
    run = script(research(), decision())
    s = go(FakeAlpaca(is_open=False), run, tmp_path)
    assert run.calls == [] and s["equity"] == 5_000.0


def test_dry_run_sends_and_saves_nothing(tmp_path):
    b = FakeAlpaca()
    s = go(b, script(research([cand("NVDA")]), decision([order("NVDA")])), tmp_path,
           dry_run=True)  # fmt: skip
    assert s["opened"] and b.sent == []
    assert not (T.folder(tmp_path) / "trader.json").exists()


def test_guards(tmp_path):
    T.save_state(T.load_state(tmp_path) | {"account": "PA9"}, tmp_path)
    with pytest.raises(GuardError, match="not PA9"):
        go(FakeAlpaca(), script(research(), decision()), tmp_path)
    T.kill_switch_path().parent.mkdir(parents=True, exist_ok=True)
    T.kill_switch_path().write_text("x")
    with pytest.raises(GuardError, match="kill switch"):
        go(FakeAlpaca(), script(research(), decision()), tmp_path)


def test_pinned_account_comes_from_the_follower(tmp_path):
    d = T.folder(tmp_path)
    d.mkdir(parents=True)
    (d / "follow.json").write_text(json.dumps({"account": "PA31", "records": {}}))
    assert T.load_state(tmp_path)["account"] == "PA31"


def test_no_new_positions_after_last_open(tmp_path):
    b = FakeAlpaca()
    s = go(b, script(research([cand("NVDA")]), decision([order("NVDA", exit_by="2026-12-24")])),
           tmp_path, today="2026-12-24", now=datetime(2026, 12, 24, 12, 0, tzinfo=NY))  # fmt: skip
    assert not s["opened"] and "no new positions" in s["rejected"][0]


# ---------------------------------------------------------------- watch (no LLM) and the lock


class WatchAlpaca(FakeAlpaca):
    """Entries can be left working (`hold_entries`); knows today's session hours."""

    def __init__(self, hold_entries=False, close="16:00", **kw):
        super().__init__(**kw)
        self.hold, self.close, self.held_specs = hold_entries, close, {}

    def session(self, day):
        return ("09:30", self.close)

    def submit(self, spec):
        if self.hold and spec.client_id.endswith("-open"):
            self.sent.append(spec)
            info = OrderInfo(spec.client_id, "new", 0.0, None, None, [])
            self.orders[spec.client_id] = info
            self.held_specs[spec.client_id] = spec
            return info
        return super().submit(spec)

    def fill_held(self):
        for cid, spec in self.held_specs.items():
            if not self.orders[cid].final:
                self._fill(spec, spec.limit)


def _clock(times):
    it = iter(times)
    return lambda: next(it)


def at(hhmm, day=DAY):
    h, m = map(int, hhmm.split(":"))
    y, mo, d = map(int, day.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=NY)


def test_check_takes_an_option_stop_during_the_day(tmp_path):
    b = WatchAlpaca()
    opt = decision([order("AMD", "option", CALL, qty=1, stop=225.0)])
    go(b, script(research([cand("AMD")]), opt), tmp_path)
    b.stock["AMD"] = (224.0, 224.2)  # 14:15: through the underlying stop
    b.opt[CALL] = (2.0, 2.2)  # the call lost most of its value
    s = T.check(b, now=at("14:15"), root=tmp_path)
    assert s["closed"] and "stop" in s["closed"][0]
    assert b.positions() == {}
    pos = next(iter(T.load_state(tmp_path)["positions"].values()))
    assert pos["status"] == "closed" and pos["realized"] < 0


def test_check_books_a_late_entry_and_puts_its_stop_at_the_broker(tmp_path):
    b = WatchAlpaca(hold_entries=True)
    go(b, script(research([cand("NVDA")]), decision([order("NVDA", qty=5)])), tmp_path)
    assert not [x for x in b.sent if x.stop is not None]  # entry still working at 13:31
    T.check(b, now=at("13:45"), root=tmp_path)  # still working: no reconcile gap raised
    b.fill_held()
    T.check(b, now=at("14:00"), root=tmp_path)
    stops = [x for x in b.sent if x.stop is not None]
    assert len(stops) == 1 and stops[0].tif == "gtc" and stops[0].qty == 5
    assert next(iter(T.load_state(tmp_path)["positions"].values()))["status"] == "open"


def test_watch_runs_until_ten_minutes_before_the_close(tmp_path):
    b = WatchAlpaca()
    times = [at("09:40")] + [at(t) for t in ("09:40", "09:40", "09:55", "09:55", "15:50")]
    n = T.watch(b, every=900, root=tmp_path, clock=_clock(times), sleep=lambda s: None)
    assert n == 2  # 09:40 and 09:55; stops at 15:50
    assert (T.folder(tmp_path) / "equity.csv").exists()


def test_watch_respects_half_days_and_closed_days(tmp_path):
    half = WatchAlpaca(close="13:00")
    times = [at("12:55"), at("12:55")]
    assert T.watch(half, root=tmp_path, clock=_clock(times), sleep=lambda s: None) == 0

    class Closed(WatchAlpaca):
        def session(self, day):
            return None

    assert T.watch(Closed(), root=tmp_path, clock=_clock([at("10:00")])) == 0


def test_watch_skips_while_a_session_holds_the_lock_and_stops_on_kill(tmp_path):
    b = WatchAlpaca()
    times = [at("10:00"), at("10:00"), at("10:00"), at("10:15"), at("10:15")]
    with T.trader_lock(tmp_path):
        n = T.watch(b, root=tmp_path, clock=_clock(times[:3] + [at("15:55")]),
                    sleep=lambda s: None)  # fmt: skip
    assert n == 0
    T.kill_switch_path().parent.mkdir(parents=True, exist_ok=True)
    T.kill_switch_path().write_text("x")
    assert T.watch(b, root=tmp_path, clock=_clock(times), sleep=lambda s: None) == 0


def test_watch_logs_a_guard_error_and_keeps_going(tmp_path, caplog):
    b = WatchAlpaca()
    T.save_state(T.load_state(tmp_path) | {"account": "PA9"}, tmp_path)
    times = [at("10:00"), at("10:00"), at("10:00"), at("15:55")]
    assert T.watch(b, root=tmp_path, clock=_clock(times), sleep=lambda s: None) == 0
    assert "GuardError" in caplog.text


def test_lock_is_exclusive_waits_and_breaks_stale_locks(tmp_path):
    with T.trader_lock(tmp_path):
        with pytest.raises(T.LockBusy):
            with T.trader_lock(tmp_path):
                pass
        with pytest.raises(T.LockBusy):  # waits, then gives up
            with T.trader_lock(tmp_path, wait=0.01, sleep=lambda s: None):
                pass
    assert not (T.folder(tmp_path) / "trader.lock").exists()  # released
    lock = T.folder(tmp_path) / "trader.lock"
    lock.write_text("pid 1")
    old = lock.stat().st_mtime - 7200
    import os

    os.utime(lock, (old, old))
    with T.trader_lock(tmp_path):  # a crashed run's lock is broken
        pass
