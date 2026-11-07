"""Are the logins the scheduled jobs depend on still alive? Alerts (ops.notify) if not.

    uv run python -m horizon_trader.ops.logins                     # IB Gateway, Codex, Claude
    uv run python -m horizon_trader.ops.logins --canary            # + one tiny `codex exec` call
    uv run python -m horizon_trader.ops.logins --notify            # alert (urgent) on any failure

Scheduled on the ops machine (deploy/windows/install_tasks.ps1): 07:30 Sun-Fri (before the
08:00 morning job and the 09:20 Gateway users; Sunday evening catches the weekly IBKR re-login
before Monday) and 14:30 Mon-Fri with --canary (before the 15:00 journal). None of the three
logins exposes an expiry date, so this catches a dead login hours before a job needs it
rather than predicting it. Read-only: the Gateway check connects with readonly=True.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess

import horizon_trader.config  # noqa: F401  (loads .env)

GATEWAY_CLIENT_ID = 51  # scanner 11, orb 31/32, noise 41: keep clear of the job clients
CANARY_MODEL = "gpt-6.1-sol"  # the journal's and the monthly scores' model
FIX = {
    "IB Gateway": "Remote into the mini, log in to IB Gateway (paper) and approve the 2FA "
    "prompt in IBKR Mobile.",
    "Codex login": "On the mini: `codex login` (ChatGPT account), then "
    "`uv run python -m horizon_trader.ops.logins --canary`.",
    "Codex canary": "On the mini: `codex login`; if it is logged in, check usage limits "
    "with an interactive `codex` session.",
    "Claude login": "On the mini: run `claude` and use /login.",
}


def row(name: str, ok: bool, detail: str) -> dict:
    return {"name": name, "status": "ok" if ok else "bad", "detail": detail}


def _cli(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    exe = shutil.which(cmd[0])  # Windows: npm shims are .cmd files
    if exe is None:
        raise FileNotFoundError(f"{cmd[0]} is not on PATH")
    return subprocess.run(
        [exe, *cmd[1:]], capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, check=False,
    )  # fmt: skip


def ib_gateway(connect=None) -> dict:
    """Logged in = the API port answers and reports a paper (DU...) account."""
    if connect is None:
        from horizon_trader.execution.ibkr import connect
    try:
        ib = connect(readonly=True, client_id=GATEWAY_CLIENT_ID)
    except Exception as exc:  # noqa: BLE001 - any failure means not usable
        return row("IB Gateway", False, f"no API connection ({type(exc).__name__}: {exc})")
    try:
        accounts = list(ib.managedAccounts())
    finally:
        ib.disconnect()
    if not accounts:
        return row("IB Gateway", False, "connected but no account: login not finished")
    if not all(a.startswith("DU") for a in accounts):
        return row("IB Gateway", False, f"not a paper account: {accounts}")
    return row("IB Gateway", True, f"connected, account {accounts[0]}")


def codex_login(run=_cli) -> dict:
    try:
        proc = run(["codex", "login", "status"])
    except Exception as exc:  # noqa: BLE001
        return row("Codex login", False, str(exc))
    text = (proc.stdout + proc.stderr).strip()
    ok = proc.returncode == 0 and "logged in" in text.lower() and "not logged" not in text.lower()
    return row("Codex login", ok, text.splitlines()[0] if text else f"exit {proc.returncode}")


def claude_login(run=_cli) -> dict:
    try:
        proc = run(["claude", "auth", "status"])
        status = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001 - not installed, or not JSON
        return row("Claude login", False, f"{type(exc).__name__}: {exc}")
    ok = bool(status.get("loggedIn"))
    return row("Claude login", ok, f"loggedIn={ok}, {status.get('authMethod', '?')}")


def codex_canary(call=None) -> dict:
    """One minimal real request: a 'logged in' status can hide an expired token or a limit."""
    if call is None:
        from horizon_trader.llm.codex import codex as call
    try:
        out = call("Reply with exactly: OK", CANARY_MODEL, effort="low", timeout=300)
    except Exception as exc:  # noqa: BLE001
        return row("Codex canary", False, f"{type(exc).__name__}: {str(exc)[-300:]}")
    text = str(out.get("result", "")).strip()
    return row("Codex canary", "OK" in text.upper(), f"{CANARY_MODEL} replied {text[:40]!r}")


def run_checks(canary: bool = False) -> list[dict]:
    rows = [ib_gateway(), codex_login(), claude_login()]
    if canary:
        rows.append(codex_canary())
    return rows


def alert(rows: list[dict]) -> tuple[str, str] | None:
    bad = [r for r in rows if r["status"] != "ok"]
    if not bad:
        return None
    names = ", ".join(r["name"] for r in bad)
    lines = []
    for r in bad:
        lines += [f"{r['name']}: {r['detail']}", f"  fix: {FIX.get(r['name'], '')}"]
    return f"horizon-trader: login needed ({names})", "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--canary", action="store_true", help="also make one tiny codex exec call")
    p.add_argument("--notify", action="store_true", help="alert (urgent) on any failure")
    a = p.parse_args(argv)
    rows = run_checks(a.canary)
    for r in rows:
        print(f"{r['status']:<5} {r['name']}: {r['detail']}")
    msg = alert(rows)
    if a.notify and msg:
        from horizon_trader.ops.notify import send

        print("alerted:", ", ".join(send(*msg, level="urgent")))
    return 1 if msg else 0


if __name__ == "__main__":
    raise SystemExit(main())
