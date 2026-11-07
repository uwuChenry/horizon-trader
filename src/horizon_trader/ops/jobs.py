"""OS-neutral scheduled jobs, shared by Task Scheduler and systemd."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from horizon_trader.config import REPO_ROOT, data_dir

NY = ZoneInfo("America/New_York")
NYSE_HOLIDAYS = frozenset(
    date.fromisoformat(value)
    for value in (
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
    )
)
JOBS = (
    "morning",
    "scanner",
    "noise",
    "observe",
    "journal",
    "options_log",
    "evening",
    "llm_monthly",
)


@dataclass(frozen=True)
class Step:
    name: str
    module: str
    args: tuple[str, ...]
    log: str
    when: Callable[[], bool] | None = None
    background: bool = False
    fatal: bool = False


def is_trading_day(today: date) -> bool:
    if today.year > max(day.year for day in NYSE_HOLIDAYS):
        print(
            f"WARNING: NYSE holiday list needs extending for {today.year}; using weekdays only.",
            flush=True,
        )
    return today.weekday() < 5 and today not in NYSE_HOLIDAYS


def _alpaca_enabled() -> bool:
    return os.environ.get("ALPACA_DAILY_BOOK_API_KEY", "").startswith("PK")


def job_steps(job: str, today: date) -> tuple[Step, ...]:
    """Keep each job's ordering, log destinations, and failure policy together."""
    massive = "horizon_trader.datasources.massive"
    scanner = "horizon_trader.intraday.scanner_log"
    competition = Step("competition", "horizon_trader.agents.competition", ("run",), "competition")
    if job == "morning":
        return (
            Step("massive day", massive, ("download", "--dataset", "day"), "morning"),
            Step(
                "llm monthly",
                "horizon_trader.ops.jobs",
                ("llm_monthly",),
                "morning",
                background=True,
            ),
            Step(
                "momentum (Alpaca paper)",
                "horizon_trader.execution.momentum_book",
                ("run",),
                "morning",
            ),
            Step("massive minute", massive, ("download", "--dataset", "minute"), "morning"),
            Step("scanner compare", scanner, ("compare",), "morning"),
        )
    if job == "scanner":
        return (Step("scanner capture", scanner, ("capture",), "scanner"),)
    if job == "noise":
        return (Step("qqq noise", "horizon_trader.intraday.noise_live", ("run",), "noise"),)
    if job == "observe":
        window = (
            "--start",
            (today - timedelta(days=7)).isoformat(),
            "--end",
            (today - timedelta(days=1)).isoformat(),
        )
        return (
            Step("recent day", massive, ("download", "--dataset", "day", *window), "observe"),
            Step("recent minute", massive, ("download", "--dataset", "minute", *window), "observe"),
            Step("observe", "horizon_trader.execution.observe", ("--session",), "observe"),
        )
    if job == "journal":
        return (Step("journal", "horizon_trader.agents.journal", ("run",), "journal"), competition)
    if job == "options_log":
        return (
            Step(
                "options capture",
                "horizon_trader.datasources.ibkr_options_log",
                ("capture",),
                "options",
            ),
        )
    if job == "evening":
        return (
            Step("shadow", "horizon_trader.run_daily", ("--mode", "shadow"), "evening"),
            Step(
                "alpaca",
                "horizon_trader.run_daily",
                ("--mode", "alpaca"),
                "evening",
                when=_alpaca_enabled,
            ),
            competition,
        )
    if job == "llm_monthly":
        return tuple(
            Step(cmd, "horizon_trader.llm.fundamentals", (cmd,), "llm-fundamentals", fatal=True)
            for cmd in ("export", "run", "check")
        )
    raise ValueError(f"Unknown job: {job}")


def _run(command: list[str], **kwargs) -> int:
    return subprocess.run(command, **kwargs, check=False).returncode


def _launch_background(command: list[str], **kwargs) -> None:
    """Detach the monthly job; only failure to launch counts against the parent job."""
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, stdin=subprocess.DEVNULL, **kwargs)


def _stamp(message: str) -> str:
    return f"=== {datetime.now(NY):%H:%M:%S} {message}"


def run_job(
    job: str,
    today: date | None = None,
    runner: Callable[..., int] | None = None,
    dry: bool = False,
    *,
    force: bool = False,
    background_launcher: Callable[..., object] | None = None,
    notifier: Callable[..., object] | None = None,
) -> int:
    """Run a job; injected runners accept subprocess kwargs and return integer exit codes.

    The background launcher has the same inputs, but its return value is ignored: a
    successful launch is exit 0, and the detached job records its own eventual failures.
    ``force`` overrides only the calendar, not the monthly or Alpaca conditions.
    ``notifier`` (``ops.notify.send``-like) gets a digest of a job that exits 0 (ops.digest);
    only ``main`` passes one, so tests and callers never post by accident.
    """
    today = today if today is not None else datetime.now(NY).date()
    steps = job_steps(job, today)
    trading_day = is_trading_day(today)
    if not trading_day:
        reason = "weekend" if today.weekday() >= 5 else "NYSE holiday"
        action = "forcing" if force else "skipping"
        print(f"{job}: {action} {today} ({reason})", flush=True)
        if not force and not dry:
            return 0

    root = data_dir()
    # Check once before export: export itself creates this month's directory.
    monthly_pending = job != "llm_monthly" or not any(
        path.is_dir() for path in (root / "llm" / "fundamental_scores").glob(f"{today:%Y-%m}-*")
    )
    if not monthly_pending:
        print(f"{job}: skipping; {today:%Y-%m} fundamental scores already started.", flush=True)
        if not dry:
            return 0

    runner = runner if runner is not None else _run
    background_launcher = (
        background_launcher if background_launcher is not None else _launch_background
    )
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    logs: dict[Path, None] = {}
    segments: dict[str, str] = {}  # step name -> log text written this run (for the digest)
    exit_code = 0
    for step in steps:
        command = [sys.executable, "-m", step.module, *step.args]
        if force and step.background:
            command.append("--force")
        log_path = root / "logs" / f"{today}-{step.log}.log"
        condition = step.when is None or step.when()
        enabled = (trading_day or force) and monthly_pending and condition
        if dry:
            print(
                f"{step.name}: run={enabled} (trading_day={trading_day}, force={force}, "
                f"monthly_pending={monthly_pending}, when={condition}); "
                f"background={step.background}; log={log_path}; command={command!r}",
                flush=True,
            )
            continue
        if not enabled:
            print(f"{step.name}: exit skipped (0.00s; condition=False)", flush=True)
            continue

        log_path.parent.mkdir(parents=True, exist_ok=True)
        logs[log_path] = None
        offset = log_path.stat().st_size if log_path.exists() else 0
        started = perf_counter()
        with log_path.open("a", encoding="utf-8") as log:
            print(_stamp(step.name), file=log, flush=True)
            try:
                kwargs = {"cwd": REPO_ROOT, "stdout": log, "stderr": subprocess.STDOUT, "env": env}
                if step.background:
                    background_launcher(command, **kwargs)
                    result = 0
                else:
                    result = runner(command, **kwargs)
            except Exception as exc:
                print(f"{step.name} failed: {type(exc).__name__}: {exc}", file=log, flush=True)
                result = 1
            background = " (background launch)" if step.background else ""
            summary = f"{step.name}: exit {result} ({perf_counter() - started:.2f}s){background}"
            print(summary, file=log, flush=True)
            print(summary, flush=True)

            # Observer history refreshes are best effort; preserve the session's actual code.
            if job == "observe":
                if step.module == "horizon_trader.datasources.massive":
                    if result:
                        dataset = step.args[2]
                        print(
                            f"Recent {dataset} download failed; observer will log stale history.",
                            file=log,
                            flush=True,
                        )
                else:
                    exit_code = result
            elif result:
                exit_code = 1
            if result and step.fatal:
                print(f"=== stopped: {' '.join(step.args)} failed", file=log, flush=True)
                segments[step.name] = _read_from(log_path, offset)
                break
        segments[step.name] = _read_from(log_path, offset)

    for log_path in logs:
        with log_path.open("a", encoding="utf-8") as log:
            print(_stamp("done"), file=log)
    if notifier is not None and exit_code == 0 and segments:
        _send_digest(job, today, root, segments, notifier)
    return exit_code


def _read_from(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _send_digest(job: str, today: date, root: Path, segments: dict, notifier: Callable) -> None:
    """Best effort: a digest problem is printed, never turned into a job failure."""
    from horizon_trader.ops import digest

    try:
        built = digest.build(job, today, root, segments)
        if built:
            notifier(built[0], built[1], "info")
    except BaseException as exc:  # noqa: BLE001 - includes SystemExit (no channel configured)
        print(f"digest not sent: {type(exc).__name__}: {exc}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", choices=JOBS)
    parser.add_argument(
        "--dry", action="store_true", help="show steps and conditions without running"
    )
    parser.add_argument("--force", action="store_true", help="run even on a non-trading day")
    args = parser.parse_args(argv)
    from horizon_trader.ops.notify import send

    return run_job(args.job, dry=args.dry, force=args.force, notifier=send)


if __name__ == "__main__":
    raise SystemExit(main())
