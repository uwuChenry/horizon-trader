"""IB Gateway watchdog: a live API probe every 5 minutes; restarts a dead or frozen Gateway.

    uv run python -m horizon_trader.ops.gateway_watchdog        # one probe (the scheduled task)
    uv run python -m horizon_trader.ops.gateway_watchdog --dry  # probe + decide, restart nothing

Why: IBC handles logins and the daily 06:45 restart, but nothing restarts a Gateway that is
still running yet useless. The "IBC Gateway (paper)" task relaunches only after the process
has exited (IgnoreNew), so these went unrecovered:
  2026-11-08 06:45  IBC's restart hung waiting for the config dialog: down ~40 hours
  2026-11-10 15:43  the Gateway froze with its port open: every request hung until 23:42

Probe: connect with a read-only client (id 52) and ask IBKR for the time, 15s timeout.
After FAILS_BEFORE_RESTART failures in a row (10 minutes) it kills the Gateway's java.exe,
stops and restarts the IBC task, and sends an urgent alert. It then waits GRACE for the
login before probing again, restarts at most MAX_RESTARTS_PER_DAY times a day (then only
alerts, e.g. during an IBKR outage), and never acts during IBC's own 06:45 restart.
Orders already at IBKR (stops included) are unaffected by a Gateway restart; a runner that
was connected exits and its position is closed at the next open (orb_live leftovers).
State: data/logs/gateway_watchdog.json; events: data/logs/<date>-watchdog.log (only when
something is wrong, so a quiet log is a healthy Gateway). Linux: `systemctl --user restart
ib-gateway` (unverified there).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from horizon_trader import config

NY = ZoneInfo("America/New_York")
CLIENT_ID = 52  # logins 51; job clients 11-41
PROBE_TIMEOUT = 15.0
FAILS_BEFORE_RESTART = 2
GRACE = timedelta(minutes=6)  # IBC login takes ~30-60s; give it room before judging again
MAX_RESTARTS_PER_DAY = 3
QUIET = (time(6, 40), time(7, 5))  # IBC's own auto restart at 06:45
IBC_TASK = "IBC Gateway (paper)"
RESTART_PS = (
    "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'java.exe' -and "
    "$_.CommandLine -match '\\\\Jts\\\\ibgateway\\\\' } | "
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }; "
    f"Stop-ScheduledTask -TaskName '{IBC_TASK}' -ErrorAction SilentlyContinue; "
    "Start-Sleep -Seconds 3; "
    f"Start-ScheduledTask -TaskName '{IBC_TASK}'"
)


def probe(connect=None, timeout: float = PROBE_TIMEOUT) -> tuple[bool, str]:
    """(ok, detail): the API answers a request, not just the port, on a paper account."""
    if connect is None:
        from horizon_trader.execution.ibkr import connect
    try:
        ib = connect(readonly=True, client_id=CLIENT_ID)
    except Exception as exc:  # noqa: BLE001 - any failure is "not usable"
        return False, f"no API connection ({type(exc).__name__}: {exc})"
    try:
        ib.RequestTimeout = timeout
        when = ib.reqCurrentTime()
        accounts = list(ib.managedAccounts())
    except Exception as exc:  # noqa: BLE001 - a frozen Gateway times out here
        return False, f"connected but not answering ({type(exc).__name__}: {exc})"
    finally:
        try:
            ib.disconnect()
        except Exception:  # noqa: BLE001
            pass
    if not accounts or not all(a.startswith("DU") for a in accounts):
        return False, f"unexpected accounts {accounts} (login unfinished or not paper)"
    return True, f"answering, server time {when}"


def decide(state: dict, ok: bool, now: datetime) -> str:
    """'ok' | 'quiet' | 'grace' | 'wait' | 'restart' | 'give_up'; updates `state` in place."""
    today = now.date().isoformat()
    if state.get("day") != today:
        state.update(day=today, restarts=0, fails=0, gave_up=False)  # no probes overnight
    if QUIET[0] <= now.time() < QUIET[1]:
        return "quiet"
    last = state.get("last_restart")
    if last and now - datetime.fromisoformat(last) < GRACE:
        return "grace"
    if ok:
        state["fails"] = 0
        return "ok"
    state["fails"] = state.get("fails", 0) + 1
    if state["fails"] < FAILS_BEFORE_RESTART:
        return "wait"
    if state["restarts"] >= MAX_RESTARTS_PER_DAY:
        return "give_up"
    state.update(fails=0, restarts=state["restarts"] + 1, last_restart=now.isoformat())
    return "restart"


def restart_gateway(run=None) -> str:
    """Kill the Gateway's java.exe, then stop and start the IBC task (Windows)."""
    run = run or subprocess.run
    if sys.platform == "win32":
        cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", RESTART_PS]
    else:
        cmd = ["systemctl", "--user", "restart", "ib-gateway"]
    proc = run(cmd, capture_output=True, text=True, timeout=60, check=False)
    out = (proc.stdout + proc.stderr).strip()
    return f"exit {proc.returncode}" + (f": {out[-300:]}" if out else "")


def state_path():
    return config.data_dir() / "logs" / "gateway_watchdog.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=1), encoding="utf-8")


def log_event(now: datetime, line: str) -> None:
    path = config.data_dir() / "logs" / f"{now:%Y-%m-%d}-watchdog.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{now:%H:%M:%S} {line}\n")
    print(line, flush=True)


def run_once(now=None, prober=probe, restarter=restart_gateway, notifier=None, dry=False):
    now = now or datetime.now(NY)
    state = load_state()
    was_restarted = bool(state.get("pending_recovery"))
    ok, detail = (True, "quiet window") if QUIET[0] <= now.time() < QUIET[1] else prober()
    action = decide(state, ok, now)
    notify = notifier or _notify
    if action == "ok" and was_restarted:
        state["pending_recovery"] = False
        log_event(now, f"recovered after restart: {detail}")
        notify("IB Gateway back after a watchdog restart", detail, "info")
    elif action == "wait":
        log_event(now, f"probe failed ({state['fails']}/{FAILS_BEFORE_RESTART}): {detail}")
    elif action == "restart":
        log_event(now, f"restarting the Gateway (restart {state['restarts']} today): {detail}")
        result = "dry run: not restarted" if dry else restarter()
        log_event(now, f"restart: {result}")
        state["pending_recovery"] = True
        notify("IB Gateway not answering: watchdog restarted it",
               f"{detail}\nrestart {state['restarts']}/{MAX_RESTARTS_PER_DAY} today; {result}",
               "urgent")  # fmt: skip
    elif action == "give_up" and not state.get("gave_up"):
        state["gave_up"] = True
        log_event(now, f"still failing after {MAX_RESTARTS_PER_DAY} restarts today: {detail}")
        notify("IB Gateway down: watchdog gave up for today",
               f"{detail}\n{MAX_RESTARTS_PER_DAY} restarts didn't fix it. Check the mini.",
               "urgent")  # fmt: skip
    if not dry:
        save_state(state)
    return action, detail


def _notify(title: str, body: str, level: str) -> None:
    try:
        from horizon_trader.ops.notify import send

        send(title, body, level)
    except BaseException as exc:  # noqa: BLE001 - SystemExit when no channel is configured
        print(f"(alert not sent: {exc!r})", flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dry", action="store_true", help="probe and decide; restart and save nothing")
    a = p.parse_args(argv)
    config.require_ops("gateway watchdog")
    action, detail = run_once(dry=a.dry)
    if a.dry:
        print(f"{action}: {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
