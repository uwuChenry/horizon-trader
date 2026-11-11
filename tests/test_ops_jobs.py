"""Scheduled-job behavior without network calls or real subprocesses."""

import json
import re
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from horizon_trader.ops import jobs

TODAY = date(2026, 11, 5)
EXPECTED = {
    "morning": [
        ("run", "datasources.massive", ["download", "--dataset", "day"], "morning"),
        ("run", "datasources.massive_ref", [], "morning"),
        ("background", "ops.jobs", ["llm_monthly"], "morning"),
        ("run", "execution.momentum_book", ["run"], "morning"),
        ("run", "datasources.massive", ["download", "--dataset", "minute"], "morning"),
        ("run", "intraday.scanner_log", ["compare"], "morning"),
    ],
    "scanner": [
        ("run", "intraday.scanner_log", ["capture"], "scanner"),
    ],
    "noise": [
        ("run", "intraday.noise_live", ["run"], "noise"),
    ],
    "orb": [
        ("run", "intraday.orb_live", ["run"], "orb"),
    ],
    "orb_alpaca": [
        ("run", "intraday.orb_alpaca", ["run"], "orb-alpaca"),
    ],
    "observe": [
        (
            "run",
            "datasources.massive",
            ["download", "--dataset", "day", "--start", "2026-10-29", "--end", "2026-11-04"],
            "observe",
        ),
        (
            "run",
            "datasources.massive",
            ["download", "--dataset", "minute", "--start", "2026-10-29", "--end", "2026-11-04"],
            "observe",
        ),
        ("run", "execution.observe", ["--session"], "observe"),
    ],
    "journal": [
        ("run", "agents.journal", ["run"], "journal"),
        ("run", "agents.competition", ["run"], "competition"),
    ],
    "options_log": [
        ("run", "datasources.ibkr_options_log", ["capture"], "options"),
    ],
    "evening": [
        ("run", "run_daily", ["--mode", "shadow"], "evening"),
        ("run", "run_daily", ["--mode", "alpaca"], "evening"),
        ("run", "agents.competition", ["run"], "competition"),
        ("run", "intraday.orb_live", ["sync"], "orb"),
    ],
    "llm_monthly": [
        ("run", "llm.fundamentals", ["export"], "llm-fundamentals"),
        ("run", "llm.fundamentals", ["run"], "llm-fundamentals"),
        ("run", "llm.fundamentals", ["check"], "llm-fundamentals"),
    ],
}
HOLIDAYS = [
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-04-03",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-26",
    "2026-12-25",
    "2027-01-01",
    "2027-01-18",
    "2027-02-15",
    "2027-03-26",
    "2027-05-31",
    "2027-06-18",
    "2027-07-05",
    "2027-09-06",
    "2027-11-25",
    "2027-12-24",
]


class FakeRunner:
    def __init__(self, results=()):
        self.results = iter(results)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append(("run", command, kwargs))
        print("child output: café", file=kwargs["stdout"], flush=True)
        result = next(self.results, 0)
        if isinstance(result, Exception):
            raise result
        return result

    def background(self, command, **kwargs):
        self.calls.append(("background", command, kwargs))
        # An opaque handle: trying to wait for it would fail the job.
        return object()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("HT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ALPACA_DAILY_BOOK_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_ORB_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("Tests must not start real subprocesses")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.mark.parametrize("job", EXPECTED)
def test_job_order_logs_and_subprocess_contract(job, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ALPACA_DAILY_BOOK_API_KEY", "PK-test")
    monkeypatch.setenv("ALPACA_ORB_API_KEY", "PK-test")
    monkeypatch.setenv("OPS_TEST_INHERITED", "present")
    fake = FakeRunner()
    assert jobs.run_job(job, TODAY, fake, background_launcher=fake.background) == 0
    expected = EXPECTED[job]
    assert len(fake.calls) == len(expected)
    for (mode, command, kwargs), (expected_mode, module, args, suffix) in zip(
        fake.calls, expected, strict=True
    ):
        assert mode == expected_mode
        assert command == [sys.executable, "-m", f"horizon_trader.{module}", *args]
        assert kwargs["cwd"] == jobs.REPO_ROOT
        assert kwargs["stderr"] == subprocess.STDOUT
        assert kwargs["env"]["PYTHONUNBUFFERED"] == "1"
        assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
        assert kwargs["env"]["OPS_TEST_INHERITED"] == "present"
        log = kwargs["stdout"]
        assert log.mode == "a"
        assert log.encoding == "utf-8"
        assert Path(log.name) == tmp_path / "logs" / f"{TODAY}-{suffix}.log"
    assert {p.name for p in (tmp_path / "logs").iterdir()} == {
        f"{TODAY}-{suffix}.log" for _, _, _, suffix in expected
    }
    for log in (tmp_path / "logs").iterdir():
        content = log.read_text(encoding="utf-8")
        assert re.search(r"^=== \d{2}:\d{2}:\d{2} \S+", content, re.MULTILINE)
        assert re.search(r"=== \d{2}:\d{2}:\d{2} done\n$", content)
        assert "child output: café" in content
    summaries = capsys.readouterr().out.splitlines()
    assert len(summaries) == len(expected)
    assert all(re.search(r"exit 0 \(\d+\.\d+s\)", line) for line in summaries)


@pytest.mark.parametrize(
    "key,enabled",
    [(None, False), ("", False), ("AK-live", False), ("pk-lowercase", False), ("PK-paper", True)],
)
def test_alpaca_condition(key, enabled, monkeypatch):
    if key is not None:
        monkeypatch.setenv("ALPACA_DAILY_BOOK_API_KEY", key)
    fake = FakeRunner()
    assert jobs.run_job("evening", TODAY, fake) == 0
    args = [command[3:] for _, command, _ in fake.calls]
    assert args == [
        ["--mode", "shadow"],
        *([["--mode", "alpaca"]] if enabled else []),
        ["run"],
        ["sync"],
    ]


@pytest.mark.parametrize("failure", [8, OSError("cannot start journal")])
def test_competition_runs_after_journal_failure(failure, tmp_path):
    fake = FakeRunner([failure, 0])
    assert jobs.run_job("journal", TODAY, fake) == 1
    assert [command[2] for _, command, _ in fake.calls] == [
        "horizon_trader.agents.journal",
        "horizon_trader.agents.competition",
    ]
    log = (tmp_path / "logs" / f"{TODAY}-journal.log").read_text(encoding="utf-8")
    assert "exit 8" in log if isinstance(failure, int) else "OSError: cannot start journal" in log


@pytest.mark.parametrize(
    "job", ["morning", "scanner", "noise", "journal", "options_log", "evening"]
)
def test_counted_failures_return_one_and_continue(job):
    fake = FakeRunner([4])
    assert jobs.run_job(job, TODAY, fake, background_launcher=fake.background) == 1
    expected_count = len(EXPECTED[job]) - (job == "evening")  # No Alpaca key.
    assert len(fake.calls) == expected_count


def test_monthly_skips_existing_month_directory(tmp_path, capsys):
    (tmp_path / "llm" / "fundamental_scores" / "2026-11-started").mkdir(parents=True)
    fake = FakeRunner()
    assert jobs.run_job("llm_monthly", TODAY, fake, force=True) == 0
    assert not fake.calls
    assert not (tmp_path / "logs").exists()
    assert "2026-11 fundamental scores already started" in capsys.readouterr().out


def test_monthly_ignores_files_and_other_months_and_checks_only_before_export(tmp_path):
    scores = tmp_path / "llm" / "fundamental_scores"
    (scores / "2026-10-01").mkdir(parents=True)
    (scores / "2026-1101").mkdir()
    (scores / "2026-11-not-a-directory").touch()
    fake = FakeRunner()

    def export_creates_directory(command, **kwargs):
        if command[-1] == "export":
            (scores / "2026-11-05").mkdir()
        return fake(command, **kwargs)

    assert jobs.run_job("llm_monthly", TODAY, export_creates_directory) == 0
    assert [command[-1] for _, command, _ in fake.calls] == ["export", "run", "check"]


@pytest.mark.parametrize("failure_index", [0, 1, 2])
@pytest.mark.parametrize("failure", [3, OSError("missing executable")])
def test_monthly_stops_on_first_failure(failure_index, failure, tmp_path):
    fake = FakeRunner([0] * failure_index + [failure])
    assert jobs.run_job("llm_monthly", TODAY, fake) == 1
    expected = ["export", "run", "check"][: failure_index + 1]
    assert [command[-1] for _, command, _ in fake.calls] == expected
    log = (tmp_path / "logs" / f"{TODAY}-llm-fundamentals.log").read_text(encoding="utf-8")
    assert f"=== stopped: {expected[-1]} failed" in log


@pytest.mark.parametrize("downloads", [(5, 6), (OSError("no day"), OSError("no minute"))])
@pytest.mark.parametrize("session,result", [(0, 0), (7, 7), (OSError("no observer"), 1)])
def test_observe_exit_code_ignores_download_failures(downloads, session, result, tmp_path):
    fake = FakeRunner([*downloads, session])
    assert jobs.run_job("observe", TODAY, fake) == result
    assert len(fake.calls) == 3
    log = (tmp_path / "logs" / f"{TODAY}-observe.log").read_text(encoding="utf-8")
    for dataset in ("day", "minute"):
        assert f"Recent {dataset} download failed; observer will log stale history." in log


@pytest.mark.parametrize("day", [*HOLIDAYS, "2026-11-07", "2026-11-08"])
def test_holiday_and_weekend_skip_and_force(day, tmp_path, capsys):
    fake = FakeRunner()
    today = date.fromisoformat(day)
    assert jobs.run_job("options_log", today, fake) == 0
    assert not fake.calls
    assert not (tmp_path / "logs").exists()
    assert "skipping" in capsys.readouterr().out
    assert jobs.run_job("options_log", today, fake, force=True) == 0
    assert len(fake.calls) == 1


@pytest.mark.parametrize("job", EXPECTED)
def test_calendar_applies_to_every_job(job):
    fake = FakeRunner()
    assert jobs.run_job(job, date(2026, 11, 26), fake, background_launcher=fake.background) == 0
    assert not fake.calls


@pytest.mark.parametrize("today,runs", [(date(2028, 1, 3), True), (date(2028, 1, 1), False)])
def test_expired_holiday_calendar_warns_and_uses_weekdays(today, runs, capsys):
    fake = FakeRunner()
    assert jobs.run_job("options_log", today, fake) == 0
    assert len(fake.calls) == int(runs)
    assert (
        "NYSE holiday list needs extending for 2028; using weekdays only" in capsys.readouterr().out
    )


@pytest.mark.parametrize("job", EXPECTED)
def test_dry_prints_every_step_and_log_without_running(job, tmp_path, capsys):
    fake = FakeRunner()
    assert jobs.run_job(job, TODAY, fake, dry=True, background_launcher=fake.background) == 0
    assert not fake.calls
    assert not list(tmp_path.iterdir())
    output = capsys.readouterr().out
    for _, module, args, suffix in EXPECTED[job]:
        assert f"horizon_trader.{module}" in output
        assert not args or repr(args[-1]) in output
        assert str(tmp_path / "logs" / f"{TODAY}-{suffix}.log") in output
    assert "trading_day=True" in output
    assert "when=" in output
    if job == "evening":
        assert "alpaca: run=False" in output
    if job == "morning":
        assert "background=True" in output


def test_dry_reports_monthly_and_calendar_conditions(tmp_path, capsys):
    (tmp_path / "llm" / "fundamental_scores" / "2026-11-01").mkdir(parents=True)
    fake = FakeRunner()
    assert jobs.run_job("llm_monthly", date(2026, 11, 7), fake, dry=True) == 0
    output = capsys.readouterr().out
    assert output.count("run=False") == 3
    assert "trading_day=False" in output
    assert "monthly_pending=False" in output
    assert not fake.calls
    assert not (tmp_path / "logs").exists()


def test_force_propagates_to_background_job():
    fake = FakeRunner()
    assert (
        jobs.run_job(
            "morning",
            date(2026, 11, 7),
            fake,
            force=True,
            background_launcher=fake.background,
        )
        == 0
    )
    assert fake.calls[2][0] == "background"
    assert fake.calls[2][1] == [
        sys.executable,
        "-m",
        "horizon_trader.ops.jobs",
        "llm_monthly",
        "--force",
    ]
    assert len(fake.calls) == 6


def test_background_launch_exception_is_logged_and_morning_continues(tmp_path):
    fake = FakeRunner()

    def broken_launcher(*args, **kwargs):
        raise OSError("cannot detach")

    assert jobs.run_job("morning", TODAY, fake, background_launcher=broken_launcher) == 1
    assert len(fake.calls) == 5
    assert fake.calls[-1][1][-1] == "compare"
    log = (tmp_path / "logs" / f"{TODAY}-morning.log").read_text(encoding="utf-8")
    assert "llm monthly failed: OSError: cannot detach" in log


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_background_launcher_detaches_without_waiting(platform, monkeypatch):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    launches = []

    def forbidden_wait(*args, **kwargs):
        pytest.fail("The background job must not be waited on or polled")

    def popen(command, **kwargs):
        launches.append((command, kwargs))
        return SimpleNamespace(wait=forbidden_wait, poll=forbidden_wait)

    monkeypatch.setattr(subprocess, "Popen", popen)
    fake = FakeRunner()
    assert jobs.run_job("morning", TODAY, fake) == 0
    assert len(fake.calls) == 5
    assert len(launches) == 1
    command, kwargs = launches[0]
    assert command == [sys.executable, "-m", "horizon_trader.ops.jobs", "llm_monthly"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["cwd"] == jobs.REPO_ROOT
    assert kwargs["stderr"] == subprocess.STDOUT
    assert kwargs["env"]["PYTHONIOENCODING"] == "utf-8"
    if platform == "win32":
        assert kwargs["creationflags"] == 0x208
        assert "start_new_session" not in kwargs
    else:
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs


def test_default_runner_preserves_observer_exit_code(monkeypatch):
    fake = FakeRunner([1, 2, 9])

    def run(command, **kwargs):
        assert kwargs.pop("check") is False
        return SimpleNamespace(returncode=fake(command, **kwargs))

    monkeypatch.setattr(subprocess, "run", run)
    assert jobs.run_job("observe", TODAY) == 9


def test_new_york_date_and_timestamps_when_host_date_is_tomorrow(monkeypatch, tmp_path):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz == jobs.NY
            return datetime(2026, 11, 6, 1, 30, 45, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(jobs, "datetime", FrozenDateTime)
    fake = FakeRunner()
    assert jobs.run_job("observe", runner=fake) == 0
    assert fake.calls[0][1][-4:] == ["--start", "2026-10-29", "--end", "2026-11-04"]
    log = (tmp_path / "logs" / "2026-11-05-observe.log").read_text(encoding="utf-8")
    assert "=== 20:30:45 recent day" in log
    assert log.endswith("=== 20:30:45 done\n")


def test_logs_append_across_runs(tmp_path):
    fake = FakeRunner()
    for _ in range(2):
        assert jobs.run_job("options_log", TODAY, fake) == 0
    log = (tmp_path / "logs" / f"{TODAY}-options.log").read_text(encoding="utf-8")
    assert log.count("child output: café") == 2
    assert log.count(" done\n") == 2


def test_cli_force_and_dry(monkeypatch, tmp_path, capsys):
    class HolidayDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 26, 8, tzinfo=tz)

    monkeypatch.setattr(jobs, "datetime", HolidayDateTime)
    fake = FakeRunner()
    monkeypatch.setattr(jobs, "_run", fake)
    assert jobs.main(["options_log"]) == 0
    assert not fake.calls
    assert jobs.main(["options_log", "--force", "--dry"]) == 0
    assert not fake.calls
    assert not (tmp_path / "logs").exists()
    assert "run=True (trading_day=False, force=True" in capsys.readouterr().out
    assert jobs.main(["options_log", "--force"]) == 0
    assert len(fake.calls) == 1


# --- digests (ops.digest): one info message per finished job -----------------------------


class LinesRunner(FakeRunner):
    """Writes given log lines for each call, like the real child processes."""

    def __init__(self, lines, results=()):
        super().__init__(results)
        self.lines = lines

    def __call__(self, command, **kwargs):
        for line in self.lines:
            print(line, file=kwargs["stdout"], flush=True)
        return super().__call__(command, **kwargs)


def _notes():
    sent = []
    return sent, lambda title, body, level: sent.append((title, body, level))


def test_evening_digest_keeps_key_lines_without_log_noise(monkeypatch):
    monkeypatch.setenv("ALPACA_DAILY_BOOK_API_KEY", "PK-test")
    sent, notifier = _notes()
    runner = LinesRunner(
        [
            "2026-11-05 18:00:01,000 INFO as of 2026-11-05, mode shadow",
            "2026-11-05 18:00:02,000 INFO daily_book_shadow: equity $4,839.35, cash $1,691.58",
            "2026-11-05 18:00:02,500 INFO sent 3 orders for the next open to the broker",
        ]
    )
    assert jobs.run_job("evening", TODAY, runner, notifier=notifier) == 0
    [(title, body, level)] = sent
    assert title == f"Evening {TODAY}" and level == "info"
    assert "[shadow]" in body and "[alpaca]" in body and "[competition]" in body
    assert "daily_book_shadow: equity $4,839.35, cash $1,691.58" in body
    assert "sent 3 orders for the next open to the broker" in body
    assert "as of" not in body and "INFO" not in body and "child output" not in body


def test_journal_digest_reads_decision(tmp_path):
    day = tmp_path / "journal" / "days" / TODAY.isoformat()
    day.mkdir(parents=True)
    decision = {
        "decision": {
            "regime": "risk_off",
            "bias": "Defensive",
            "debate_winner": "bear",
            "thesis": "x" * 600,
            "forecasts": [
                {"ticker": "SPY", "horizon_days": 1, "direction": "up", "confidence": 1},
                {"ticker": "QQQ", "horizon_days": 5, "direction": "down", "confidence": 3},
            ],
        },
        "resolution": [
            {
                "n": 0,
                "idea": {"structure": "put_debit_spread", "underlying": "QQQ"},
                "status": "opened",
                "reason": "ok",
            }
        ],
        "problems": ["missing mandatory forecast SPY 20d"],
        "closed_by_trader": [],
    }
    (day / "decision.json").write_text(json.dumps(decision), encoding="utf-8")
    sent, notifier = _notes()
    assert jobs.run_job("journal", TODAY, FakeRunner(), notifier=notifier) == 0
    [(title, body, _)] = sent
    assert title == f"Journal {TODAY}"
    assert body.startswith("risk_off | debate: bear\nDefensive\nSPY: 1d up(1)\nQQQ: 5d down(3)")
    assert "idea 1: put_debit_spread QQQ -> opened (ok)" in body
    assert "problem: missing mandatory forecast SPY 20d" in body
    assert "thesis: " + "x" * 397 + "..." in body
    assert "[journal]" not in body


def test_no_digest_on_failure_for_skipped_jobs_or_without_notifier():
    sent, notifier = _notes()
    assert jobs.run_job("evening", TODAY, FakeRunner([3]), notifier=notifier) == 1
    assert jobs.run_job("scanner", TODAY, FakeRunner(), notifier=notifier) == 0
    assert jobs.run_job("evening", date(2026, 11, 7), FakeRunner(), notifier=notifier) == 0
    assert sent == []
    assert jobs.run_job("evening", TODAY, FakeRunner()) == 0  # no notifier: nothing to call


@pytest.mark.parametrize("error", [RuntimeError("discord down"), SystemExit("no channel")])
def test_digest_failure_never_fails_the_job(error, capsys):
    def notifier(*args):
        raise error

    assert jobs.run_job("options_log", TODAY, FakeRunner(), notifier=notifier) == 0
    assert "digest not sent" in capsys.readouterr().out
