"""QQQ noise-area runner on Alpaca paper (intraday/noise_live.py): the plan matches the backtest,
and a scripted day sends the right orders once, with a fake Alpaca, feed and clock."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from horizon_trader.execution.alpaca_broker import LegFill, OrderInfo
from horizon_trader.execution.ledger import Ledger
from horizon_trader.intraday import market_momentum as MM
from horizon_trader.intraday import noise_live as NL

NY = "America/New_York"


def history(days: int = 20, seed: int = 0):
    """Synthetic Massive-style minute and day frames for QQQ."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2026-09-01", periods=days)
    rows, daily = [], []
    px = 100.0
    for d in dates:
        start = pd.Timestamp(d.date()).tz_localize(NY) + pd.Timedelta(hours=9.5)
        path = px * np.cumprod(1 + rng.normal(0, 0.0008, 390))
        for j, c in enumerate(path):
            rows.append({"ticker": "QQQ", "ts": start + pd.Timedelta(minutes=j), "open": c,
                         "high": c * 1.0005, "low": c * 0.9995, "close": c, "volume": 1000.0,
                         "date": d})  # fmt: skip
        daily.append({"ticker": "QQQ", "open": path[0], "close": path[-1], "date": d})
        px = path[-1] * (1 + rng.normal(0, 0.002))
    return pd.DataFrame(rows), pd.DataFrame(daily)


def test_plan_matches_the_backtest_row():
    minute, daily = history()
    bars = MM.make_bars(minute, daily)
    day = bars.close.index[-1]
    plan = NL.plan_day(minute, daily, day.strftime("%Y-%m-%d"), 390)
    sigma = MM.noise_sigma(bars.close, bars.daily["open"]).loc[day]
    for j in plan.checks:
        assert plan.sigma[j] == pytest.approx(sigma[j], rel=1e-12)
    assert plan.vol == pytest.approx(MM.daily_vol(bars.daily).loc[day], rel=1e-12)
    assert plan.prev_close == pytest.approx(bars.daily.loc[day, "prev_close"])
    assert plan.history_end == bars.close.index[-2].strftime("%Y-%m-%d")


def test_half_day_stops_checks_before_the_close():
    plan = NL.DayPlan("2026-11-27", 210, 100.0, 0.01, {j: 0.001 for j in MM.CHECKS}, "x")
    assert plan.checks[-1] == 179  # 12:30, the last check before a 13:00 close
    assert NL.hhmm(179) == "1230"


def test_sizing_uses_the_vol_target_and_the_cap():
    plan = NL.DayPlan("d", 390, 100.0, 0.01, {}, "x")
    assert plan.leverage() == 2.0 and plan.shares(5000, 100.0) == 100
    assert NL.DayPlan("d", 390, 100.0, 0.001, {}, "x").leverage() == 4.0


# ---------------------------------------------------------------- a scripted day

DAY = "2026-11-06"
OPEN = pd.Timestamp(f"{DAY} 09:30", tz=NY)


def price_at(j: int) -> float:
    if j <= 29:
        return 100 + j / 29  # up to 101 at 10:00 -> long
    if j <= 59:
        return 101 - 2 * (j - 29) / 30  # down to 99 at 10:30 -> short (reversal)
    if j < 330:
        return 100.0  # inside the band -> flat from 11:00
    return 100 + min(1.5, (j - 329) * 0.1)  # 101.5 by 15:30 -> long into the close


class FakeClock:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += pd.Timedelta(seconds=max(seconds, 0))


class FakeFeed:
    name = "fake"

    def bars(self, open_ts, now):
        rows = [{"ts": open_ts + pd.Timedelta(minutes=j), "open": price_at(j),
                 "high": price_at(j), "low": price_at(j), "close": price_at(j), "volume": 100.0}
                for j in range(390)]  # fmt: skip
        return NL._to_frame(rows, open_ts, now)


class FakeAlpaca:
    """Market orders fill at once at the scripted price; opening orders fill at 09:30;
    tags in `expire` end "expired" unfilled."""

    def __init__(self, clock):
        self.clock, self.orders, self.sent, self.held = clock, {}, [], 0.0
        self.expire = set()

    def account(self):
        return {"account": "PA9"}

    def positions(self):
        return {"QQQ": self.held} if self.held else {}

    def submit(self, spec):
        self.sent.append(spec)
        leg = spec.legs[0]
        if spec.client_id.split(DAY + "-")[1] in self.expire:
            info = OrderInfo(spec.client_id, "expired", 0.0, None, None,
                             [LegFill("QQQ", leg.side, 0.0, None)])  # fmt: skip
        elif spec.tif == "opg":
            info = OrderInfo(spec.client_id, "accepted", 0.0, None, None,
                             [LegFill("QQQ", leg.side, 0.0, None)])  # fmt: skip
        else:
            j = int((self.clock.now() - OPEN) / pd.Timedelta(minutes=1))
            info = self._fill(spec, price_at(j))
        self.orders[spec.client_id] = info
        return info

    def _fill(self, spec, price):
        leg = spec.legs[0]
        self.held += spec.qty if leg.side == "buy" else -spec.qty
        return OrderInfo(spec.client_id, "filled", spec.qty, price, str(self.clock.now())[:19],
                         [LegFill("QQQ", leg.side, spec.qty, price)])  # fmt: skip

    def order(self, cid):
        info = self.orders.get(cid)
        if info is not None and info.status == "accepted" and self.clock.now() >= OPEN:
            spec = next(s for s in self.sent if s.client_id == cid)
            info = self.orders[cid] = self._fill(spec, 99.0)
        return info


def plan():
    return NL.DayPlan(DAY, 390, 100.0, 0.01, {j: 0.001 for j in MM.CHECKS}, "2026-11-05")


def run_day(tmp_path, api=None, start="09:20", broker=None):
    clock = FakeClock(pd.Timestamp(f"{DAY} {start}", tz=NY))
    api = api or FakeAlpaca(clock)
    api.clock = clock
    ledger = Ledger.load(NL.LEDGER, 5000.0, tmp_path)
    runner = NL.Runner(api, [FakeFeed()], ledger, plan(), OPEN, clock, broker)
    runner.recover()
    runner.run()
    return api, ledger


def test_scripted_day_sends_each_order_once_and_ends_flat(tmp_path):
    api, ledger = run_day(tmp_path)
    got = [(s.client_id.split(DAY + "-")[1], s.legs[0].side, s.qty, s.tif) for s in api.sent]
    assert got == [
        ("1000-e", "buy", 100, "day"),
        ("1030-x", "sell", 100, "day"), ("1030-e", "sell", 100, "day"),
        ("1100-x", "buy", 100, "day"),
        ("1530-e", "buy", 100, "day"),
        ("close1", "sell", 100, "day"),  # day market order at 15:55, not market-on-close
    ]  # fmt: skip
    assert ledger.holdings == {} and api.held == 0
    fills = ledger.fills()
    assert len(fills) == 6 and fills["quantity"].sum() == 0
    # P&L: long 100->101 = +... is path-dependent; cash must equal the signed fill sum
    assert ledger.cash == pytest.approx(5000 - (fills["quantity"] * fills["price"]).sum())


def test_restart_books_what_was_sent_and_resends_nothing(tmp_path):
    api, ledger = run_day(tmp_path)
    n = len(api.sent)
    Ledger.load(NL.LEDGER, 5000.0, tmp_path)
    api2, ledger2 = run_day(tmp_path, api=api)
    assert len(api2.sent) == n and ledger2.holdings == {}
    assert len(ledger2.fills()) == 6  # nothing booked twice


def test_late_start_skips_the_passed_checks(tmp_path):
    api, _ = run_day(tmp_path, start="11:15")
    tags = [s.client_id.split(DAY + "-")[1] for s in api.sent]
    assert tags == ["1530-e", "close1"]


def test_close_goes_out_at_1555(tmp_path):
    api, _ = run_day(tmp_path)
    close = api.orders[f"qqqnoise-{DAY}-close1"]
    assert close.filled_at == f"{DAY} 15:55:00"


def test_expired_close_is_resent_then_alerts_after_three(tmp_path, monkeypatch, caplog):
    alerts = []
    monkeypatch.setattr(NL.Runner, "alert", lambda self, *a: alerts.append(a))
    clock = FakeClock(pd.Timestamp(f"{DAY} 09:20", tz=NY))
    api = FakeAlpaca(clock)
    api.expire.add("close1")
    api, ledger = run_day(tmp_path, api=api)
    tags = [s.client_id.split(DAY + "-")[1] for s in api.sent]
    assert tags[-2:] == ["close1", "close2"] and ledger.holdings == {} and alerts == []

    tmp2 = tmp_path / "b"
    api = FakeAlpaca(clock)
    api.expire |= {"close1", "close2", "close3"}
    api, ledger = run_day(tmp2, api=api)
    tags = [s.client_id.split(DAY + "-")[1] for s in api.sent]
    assert tags[-3:] == ["close1", "close2", "close3"]
    assert ledger.holdings == {"QQQ": 100.0} and len(alerts) == 1
    assert "after the close" in caplog.text


def test_leftover_is_closed_at_the_open_before_the_checks(tmp_path):
    Ledger(NL.LEDGER, 4400.0, holdings={"QQQ": 6.0}, root=tmp_path).save()
    clock = FakeClock(pd.Timestamp(f"{DAY} 09:25", tz=NY))
    api = FakeAlpaca(clock)
    api.held = 6.0
    api, ledger = run_day(tmp_path, api=api, start="09:25")
    first = api.sent[0]
    assert first.client_id == f"qqqnoise-{DAY}-left" and first.tif == "opg"
    assert first.legs[0].side == "sell" and first.qty == 6
    assert ledger.fills().iloc[0]["quantity"] == -6
    assert ledger.holdings == {} and api.held == 0


def test_leftover_after_0928_uses_a_day_market(tmp_path):
    Ledger(NL.LEDGER, 4400.0, holdings={"QQQ": -3.0}, root=tmp_path).save()
    clock = FakeClock(pd.Timestamp(f"{DAY} 09:45", tz=NY))
    api = FakeAlpaca(clock)
    api.held = -3.0
    api, _ = run_day(tmp_path, api=api, start="09:45")
    assert (api.sent[0].tif, api.sent[0].legs[0].side) == ("day", "buy")


class BlockAll:
    def check(self, orders, prices):
        from horizon_trader.execution.ibkr_broker import GuardError

        raise GuardError("kill switch is on")


def test_kill_switch_blocks_entries_only(tmp_path):
    api, ledger = run_day(tmp_path, broker=BlockAll())
    assert api.sent == [] and ledger.holdings == {}
    log = (Ledger.directory(NL.LEDGER, tmp_path) / "checks.jsonl").read_text(encoding="utf-8")
    assert "entry_blocked" in log


def test_a_feed_failure_keeps_the_position_and_falls_back():
    class Broken:
        name = "ibkr"

        def bars(self, open_ts, now):
            raise ConnectionRefusedError("gateway down")

    df, src = NL.live_bars([Broken(), FakeFeed()], OPEN, OPEN + pd.Timedelta(minutes=31))
    assert src == "fake" and df.index[-1] == 30  # only finished bars
    with pytest.raises(RuntimeError, match="gateway down"):
        NL.live_bars([Broken()], OPEN, OPEN + pd.Timedelta(minutes=31))


def test_stale_history_means_no_trading(monkeypatch):
    minute, daily = history(days=20)

    class Cal:
        def session(self, day):
            return None if pd.Timestamp(day).weekday() >= 5 else ("09:30", "16:00")

    monkeypatch.setattr(MM, "load_bars", lambda t: (minute, daily))
    last = daily["date"].max()
    later = (last + pd.offsets.BDay(3)).date()  # two sessions missing
    got, why = NL.setup(Cal(), later)
    assert got is None and "no trading today" in why
    got, why = NL.setup(Cal(), (last + pd.offsets.BDay(1)).date())
    assert got is not None and got[0].history_end == last.strftime("%Y-%m-%d")
