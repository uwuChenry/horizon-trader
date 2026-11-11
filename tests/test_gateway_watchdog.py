"""IB Gateway watchdog: probe, restart decisions, limits, alerts. No network, no processes."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from horizon_trader.ops import gateway_watchdog as W

NY = ZoneInfo("America/New_York")


def at(hhmm, day="2026-11-11"):
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=NY)


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    return tmp_path


class FakeIB:
    def __init__(self, answer=True, accounts=("DU1",)):
        self.answer, self.accounts, self.disconnected = answer, list(accounts), False

    def reqCurrentTime(self):
        if not self.answer:
            raise TimeoutError()
        return "2026-11-11 10:00:00"

    def managedAccounts(self):
        return self.accounts

    def disconnect(self):
        self.disconnected = True


def test_probe_needs_an_answer_not_just_a_connection():
    ib = FakeIB()
    ok, detail = W.probe(connect=lambda readonly, client_id: ib)
    assert ok and "answering" in detail and ib.disconnected
    frozen = FakeIB(answer=False)
    ok, detail = W.probe(connect=lambda readonly, client_id: frozen)
    assert not ok and "not answering" in detail and frozen.disconnected
    ok, detail = W.probe(connect=lambda **k: (_ for _ in ()).throw(ConnectionRefusedError()))
    assert not ok and "no API connection" in detail
    ok, _ = W.probe(connect=lambda readonly, client_id: FakeIB(accounts=("U123",)))
    assert not ok  # never accept a live account


def test_two_failures_then_restart_then_grace_then_limit():
    s = {}
    assert W.decide(s, True, at("10:00")) == "ok"
    assert W.decide(s, False, at("10:05")) == "wait"
    assert W.decide(s, False, at("10:10")) == "restart" and s["restarts"] == 1
    assert W.decide(s, False, at("10:15")) == "grace"  # login still running
    assert W.decide(s, False, at("10:20")) == "wait"
    assert W.decide(s, False, at("10:25")) == "restart"
    assert W.decide(s, False, at("10:35")) == "wait"
    assert W.decide(s, False, at("10:40")) == "restart"
    assert s["restarts"] == W.MAX_RESTARTS_PER_DAY
    assert W.decide(s, False, at("10:45")) == "grace"
    assert W.decide(s, False, at("10:50")) == "wait"
    assert W.decide(s, False, at("11:00")) == "give_up"
    assert W.decide(s, False, at("10:00", "2026-11-12")) == "wait"  # new day resets the count
    assert s["restarts"] == 0


def test_a_success_resets_the_failure_count():
    s = {}
    W.decide(s, False, at("10:00"))
    W.decide(s, True, at("10:05"))
    assert W.decide(s, False, at("10:10")) == "wait"


def test_quiet_during_ibc_auto_restart():
    assert W.decide({}, False, at("06:45")) == "quiet"
    assert W.decide({}, False, at("07:05")) == "wait"


def test_run_once_restarts_alerts_and_reports_recovery(data):
    alerts, restarts = [], []

    def go(t, ok):
        return W.run_once(now=at(t), prober=lambda: (ok, "x" if ok else "frozen"),
                          restarter=lambda: restarts.append(t) or "exit 0",
                          notifier=lambda *a: alerts.append(a))  # fmt: skip

    go("10:00", False)
    assert alerts == [] and restarts == []
    assert go("10:05", False)[0] == "restart" and restarts == ["10:05"]
    assert alerts[-1][2] == "urgent" and "restarted" in alerts[-1][0]
    go("10:15", True)
    assert alerts[-1][2] == "info" and "back" in alerts[-1][0]
    log = (data / "logs" / "2026-11-11-watchdog.log").read_text(encoding="utf-8")
    assert "restarting the Gateway" in log and "recovered" in log


def test_quiet_log_when_healthy(data):
    W.run_once(now=at("10:00"), prober=lambda: (True, "ok"), notifier=lambda *a: None)
    assert not (data / "logs" / "2026-11-11-watchdog.log").exists()


def test_dry_run_restarts_nothing_and_saves_nothing(data):
    W.save_state({"day": "2026-11-11", "fails": 1, "restarts": 0})
    called = []
    action, _ = W.run_once(now=at("10:00"), prober=lambda: (False, "down"),
                           restarter=lambda: called.append(1), notifier=lambda *a: None,
                           dry=True)  # fmt: skip
    assert action == "restart" and called == []
    assert W.load_state()["fails"] == 1


def test_give_up_alerts_once_per_day(data):
    W.save_state({"day": "2026-11-11", "fails": 1, "restarts": W.MAX_RESTARTS_PER_DAY})
    alerts = []
    for t in ("12:00", "12:05", "12:10"):
        W.run_once(now=at(t), prober=lambda: (False, "down"), notifier=lambda *a: alerts.append(a))
    assert len(alerts) == 1 and "gave up" in alerts[0][0]


def test_restart_command_kills_only_the_gateway_java_and_restarts_ibc(monkeypatch):
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(W.sys, "platform", "win32")
    assert W.restart_gateway(run=run) == "exit 0"
    script = seen[0][-1]
    assert "java.exe" in script and "Jts" in script and "ibgateway" in script
    assert script.index("Stop-ScheduledTask") < script.index("Start-ScheduledTask")
    assert f"'{W.IBC_TASK}'" in script


def test_grace_uses_the_saved_restart_time():
    last = (at("10:00") - timedelta(minutes=2)).isoformat()
    s = {"day": "2026-11-11", "restarts": 1, "last_restart": last}
    assert W.decide(s, False, at("10:00")) == "grace"


def test_health_row_reports_watchdog_restarts(data):
    from datetime import date

    from horizon_trader.ops import health as H

    assert H.watchdog(data, date(2026, 11, 11))["status"] == "warn"  # no state yet
    W.save_state({"day": "2026-11-11", "restarts": 0, "fails": 0})
    assert H.watchdog(data, date(2026, 11, 11))["status"] == "ok"
    W.save_state({"day": "2026-11-11", "restarts": 2, "last_restart": "x"})
    row = H.watchdog(data, date(2026, 11, 11))
    assert row["status"] == "warn" and "2x" in row["detail"]
    assert H.watchdog(data, date(2026, 11, 12))["status"] == "ok"  # yesterday's restarts
    W.save_state({"day": "2026-11-11", "restarts": 3, "gave_up": True})
    assert H.watchdog(data, date(2026, 11, 11))["status"] == "bad"
