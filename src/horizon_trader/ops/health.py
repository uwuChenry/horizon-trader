"""Health of the always-on jobs, shared by the dashboard's Live page and the ops alerts.

    uv run python -m horizon_trader.ops.health                      # print every check
    uv run python -m horizon_trader.ops.health --notify             # push anything not ok to ntfy
    uv run python -m horizon_trader.ops.health --notify --failed X  # job X failed: add its log tail

--notify posts to https://ntfy.sh/<NTFY_TOPIC> (or NTFY_URL, for a self-hosted server). The
topic name is the only secret, so pick a long random one. Read-only otherwise: nothing here
talks to a broker.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from horizon_trader import config

NY = ZoneInfo("America/New_York")
# Log files each scheduled job writes (data/logs/<date>-<suffix>.log); see ops/jobs.py.
LOG_SUFFIXES = {
    "morning": ["morning"],
    "observe": ["observe"],
    "journal": ["journal", "competition"],
    "options_log": ["options"],
    "evening": ["evening", "competition"],
    "llm_monthly": ["llm-fundamentals"],
}
DISK_WARN, DISK_BAD = 0.15, 0.05  # free share of the data disk


def business_days_between(a: date, b: date) -> int:
    """Weekdays strictly after a up to and including b (holidays not excluded)."""
    if b <= a:
        return 0
    return int(len(pd.bdate_range(a + timedelta(days=1), b)))


def observations(days: int = 14) -> dict:
    root = config.data_dir() / "live" / "observations"
    files = sorted(root.glob("*.jsonl"))[-days:]
    per_day, last_event = [], None
    for f in files:
        kinds: dict[str, int] = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kinds[event.get("kind", "?")] = kinds.get(event.get("kind", "?"), 0) + 1
            if event.get("kind") in {"connected", "connection_failed", "account"}:
                last_event = event
        per_day.append({"date": f.stem, "kinds": kinds})
    return {"days": per_day, "last_connection": last_event}


def check(name: str, last: date | None, today: date, warn_after: int, what: str) -> dict:
    if last is None:
        return {"name": name, "status": "bad", "detail": f"No {what} yet", "last": None}
    lag = business_days_between(last, today)
    status = "ok" if lag <= warn_after else "warn" if lag <= warn_after + 3 else "bad"
    return {
        "name": name,
        "status": status,
        "detail": f"Last {what} {last.isoformat()} ({lag} trading day{'s' * (lag != 1)} ago)",
        "last": last.isoformat(),
    }


def _latest_stem(paths) -> date | None:
    stems = []
    for p in paths:
        try:
            stems.append(date.fromisoformat(p.stem))
        except ValueError:
            continue
    return max(stems, default=None)


def disk(path=None) -> dict:
    usage = shutil.disk_usage(path or config.data_dir())
    free = usage.free / usage.total
    status = "ok" if free > DISK_WARN else "warn" if free > DISK_BAD else "bad"
    return {"name": "Data disk", "status": status,
            "detail": f"{usage.free / 1e9:,.0f} GB free ({free:.0%})", "last": None}  # fmt: skip


def today_ny() -> date:
    return datetime.now(NY).date()


def health(today: date | None = None) -> list[dict]:
    today = today or today_ny()
    data = config.data_dir()
    out = []
    for folder in sorted((data / "live").glob("*/equity.csv")):
        eq = pd.read_csv(folder, usecols=["date"], parse_dates=["date"])
        last = eq["date"].max().date() if len(eq) else None
        out.append(check(f"{folder.parent.name} ledger", last, today, 1, "ledger update"))
    out.append(
        check(
            "Massive daily download",
            _latest_stem((data / "massive" / "day").glob("*/*.parquet")),
            today,
            1,
            "daily file",
        )
    )
    out.append(
        check(
            "IBKR scanner log",
            _latest_stem((data / "live" / "scanner").glob("*.json")),
            today,
            1,
            "scanner capture",
        )
    )
    chains = [d for d in (data / "ibkr" / "options").glob("????-??-??") if any(d.glob("*.parquet"))]
    out.append(check("IBKR option-chain log", _latest_stem(chains), today, 1, "chain snapshot"))
    obs = observations(5)["last_connection"]
    if obs is None:
        out.append(
            {"name": "IB Gateway", "status": "bad", "detail": "No observations", "last": None}
        )
    else:
        ok = obs.get("kind") in {"connected", "account"}
        when = obs.get("observed_utc", "")[:16].replace("T", " ")
        detail = "connected" if ok else f"{obs.get('error') or obs.get('kind')}"
        out.append({"name": "IB Gateway", "status": "ok" if ok else "warn",
                    "detail": f"{detail} at {when} UTC", "last": when[:10]})  # fmt: skip
    if (data / "journal").exists():  # a missing day usually means the Claude login expired
        days = [d for d in (data / "journal" / "days").glob("????-??-??")
                if (d / "decision.json").exists()]  # fmt: skip
        out.append(check("Forecast journal (15:00, Claude login)", _latest_stem(days), today, 1,
                         "journal decision"))  # fmt: skip
    runs = sorted(p.name for p in (data / "llm" / "fundamental_scores").glob("????-??-??"))
    if runs:
        last = date.fromisoformat(runs[-1])
        due = (last.year, last.month) < (today.year, today.month)
        out.append(
            {
                "name": "LLM fundamentals (monthly)",
                "status": "warn" if due else "ok",
                "detail": f"Last run {last.isoformat()}"
                + (f"; {today:%B}'s run is due (never back-fill)" if due else ""),
                "last": last.isoformat(),
            }
        )
    out.append(disk(data))
    return out


def log_tail(job: str, today: date | None = None, lines: int = 20) -> str:
    """The last `lines` lines of each log the job writes today."""
    today = today or today_ny()
    parts = []
    for suffix in LOG_SUFFIXES.get(job, [job]):
        path = config.data_dir() / "logs" / f"{today.isoformat()}-{suffix}.log"
        if path.exists():
            tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
            parts.append(f"--- {path.name}\n" + "\n".join(tail))
    return "\n".join(parts) or f"(no log for {job} today)"


def message(rows: list[dict], failed: str | None = None, today: date | None = None):
    """(title, body, priority) for a push, or None when there is nothing to report."""
    problems = [r for r in rows if r["status"] != "ok"]
    if not problems and not failed:
        return None
    lines = [f"[{r['status']}] {r['name']}: {r['detail']}" for r in problems]
    if failed:
        title = f"horizon-trader: job {failed} failed"
        lines = [log_tail(failed, today), "", *lines]
    else:
        title = f"horizon-trader: {len(problems)} health problem{'s' * (len(problems) != 1)}"
    bad = failed or any(r["status"] == "bad" for r in problems)
    return title, "\n".join(lines).strip(), "high" if bad else "default"


def push(title: str, body: str, priority: str = "default") -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        raise SystemExit("NTFY_TOPIC is not set in .env; can't push")
    url = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/") + "/" + topic
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8")[:4000],
        headers={
            "Title": title.encode("ascii", "replace").decode(),
            "Priority": priority,
            "Tags": "warning",
        },  # fmt: skip
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        resp.read()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--notify", action="store_true", help="push problems to ntfy (NTFY_TOPIC)")
    p.add_argument("--failed", metavar="JOB", help="a scheduled job that just failed")
    a = p.parse_args(argv)
    rows = health()
    for r in rows:
        print(f"{r['status']:<5} {r['name']}: {r['detail']}")
    msg = message(rows, a.failed)
    if a.notify and msg:
        push(*msg)
        print(f"pushed: {msg[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
