"""ops.health: the checks behind the Live page and the ntfy alerts."""

from collections import namedtuple
from datetime import date

import pytest

from horizon_trader.ops import health as H
from horizon_trader.ops import notify as N

TODAY = date(2026, 11, 5)  # a Thursday


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    return tmp_path


def test_check_lag_thresholds():
    assert H.check("x", date(2026, 11, 4), TODAY, 1, "y")["status"] == "ok"
    assert H.check("x", date(2026, 11, 2), TODAY, 1, "y")["status"] == "warn"
    assert H.check("x", date(2026, 10, 20), TODAY, 1, "y")["status"] == "bad"
    assert H.check("x", None, TODAY, 1, "y")["status"] == "bad"


def test_health_on_empty_data_dir_flags_missing_jobs(data):
    rows = {r["name"]: r for r in H.health(TODAY)}
    assert rows["Massive daily download"]["status"] == "bad"
    assert rows["IB Gateway"]["status"] == "bad"
    assert "Data disk" in rows


def test_disk_thresholds(monkeypatch, data):
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(H.shutil, "disk_usage", lambda p: usage(100e9, 97e9, 3e9))
    assert H.disk()["status"] == "bad"
    monkeypatch.setattr(H.shutil, "disk_usage", lambda p: usage(100e9, 50e9, 50e9))
    assert H.disk()["status"] == "ok"


def test_message_quiet_when_all_ok():
    assert H.message([{"name": "a", "status": "ok", "detail": ""}]) is None


def test_message_lists_problems_and_priority():
    rows = [{"name": "a", "status": "ok", "detail": ""},
            {"name": "b", "status": "warn", "detail": "late"}]  # fmt: skip
    title, body, prio = H.message(rows)
    assert title == "horizon-trader: 1 health problem"
    assert body == "[warn] b: late" and prio == "default"
    rows.append({"name": "c", "status": "bad", "detail": "gone"})
    assert H.message(rows)[2] == "high"


def test_failed_job_includes_log_tail(data):
    logs = data / "logs"
    logs.mkdir()
    lines = [f"line {i}" for i in range(30)]
    (logs / "2026-11-05-journal.log").write_text("\n".join(lines), encoding="utf-8")
    (logs / "2026-11-05-competition.log").write_text("boom", encoding="utf-8")
    title, body, prio = H.message([], failed="journal", today=TODAY)
    assert title == "horizon-trader: job journal failed" and prio == "high"
    assert "line 29" in body and "line 9\n" not in body and "boom" in body


def test_log_suffixes_cover_every_job():
    from horizon_trader.ops import jobs

    assert set(H.LOG_SUFFIXES) == set(jobs.JOBS)


def test_push_posts_to_ntfy(monkeypatch):
    sent = []
    monkeypatch.setenv("NTFY_TOPIC", "ht-secret-topic")
    monkeypatch.setattr(N, "_post", lambda url, data, headers: sent.append((url, data, headers)))
    assert H.push("horizon-trader: test", "body", "high") == ["ntfy"]
    url, data, headers = sent[0]
    assert url == "https://ntfy.sh/ht-secret-topic" and data == b"body"
    assert headers["Title"] == "horizon-trader: test" and headers["Priority"] == "high"


def test_push_without_channel_refuses():
    with pytest.raises(SystemExit, match="DISCORD_WEBHOOK_URL"):
        H.push("t", "b")


def test_daily_sends_all_ok_only_with_flag(monkeypatch):
    sent = []
    monkeypatch.setattr(H, "health", lambda: [{"name": "a", "status": "ok", "detail": ""}])
    monkeypatch.setattr(H, "push", lambda *m: sent.append(m))
    H.main(["--notify"])
    assert sent == []
    H.main(["--notify", "--daily"])
    assert sent == [("horizon-trader: all 1 checks OK", "", "low")]
