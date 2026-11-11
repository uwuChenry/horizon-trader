"""One Discord/ntfy summary per finished scheduled job: what it did, not just that it ran.

`ops.jobs.main` calls `build()` after a job exits 0 and sends the result at "info" level (no
@mention). Failures already alert through `ops.health --failed`, so they get no digest. Scanner and
observe runs are left out (the 18:30 health report covers them).

The summary is built from what the job wrote: the key lines of each step's log segment (orders
sent, fills booked, equity, targets, warnings) and, for the journal, today's decision.json.
Read-only and best effort: a digest that can't be built is skipped, never a job failure.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

DIGEST_JOBS = {
    "morning": "Morning",
    "noise": "QQQ noise",
    "orb": "ORB (IBKR paper)",
    "orb_alpaca": "ORB (Alpaca paper)",
    "journal": "Journal",
    "contest": "AI contest",
    "contest_watch": "AI contest watch",
    "options_log": "Option chains",
    "evening": "Evening",
    "llm_monthly": "LLM fundamentals",
}

# Lines worth reading on a phone, from run_daily, momentum_book, noise_live, competition,
# orb_live, orb_alpaca, ibkr_options_log and llm.fundamentals (see their log.info/print calls).
KEEP = re.compile(
    r"sent \d+ orders|already (sent|queued)|new fills booked|fills booked|equity \$|targets: "
    r"|split applied|isn't tradable|rounds to 0|kill switch|entry blocked|unfilled|-> target"
    r"|underlyings captured|batches valid|top 20:|market closed|still working|DRY RUN"
    r"|pending orders filled|queued \d+ shadow|Traceback|[A-Za-z]+Error:|[1-9]\d* failed|failed:"
    r"|candidates|plan: |orders: |entry filled|stopped out|sent MOC|no fill|not flat"
    r"|not shortable|decision|opened: |closed: |rejected: |updated: "
)
# IBKR's per-contract "no security definition" errors are routine during the option capture.
DROP = re.compile(r"ib_async|^\+ |^At line:|^\s*\+ ~")
PREFIX = re.compile(r"^(uv(\.exe)? : )?\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ (INFO|WARNING|ERROR) ")
PER_STEP = 12  # keep the last N key lines of each step


def key_lines(text: str, limit: int = PER_STEP) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.lstrip("\ufeff")
        if KEEP.search(line) and not DROP.search(line):
            line = PREFIX.sub("", line).strip()
            if line:
                out.append(line)
    return out[-limit:]


def _forecasts(fc: list[dict]) -> list[str]:
    rows: dict[str, list[str]] = {}
    for f in fc:
        cell = f"{f['horizon_days']}d {f['direction']}({f.get('confidence', '?')})"
        rows.setdefault(f["ticker"], []).append(cell)
    return [f"{t}: " + "  ".join(cells) for t, cells in rows.items()]


def journal_lines(root: Path, today: date) -> list[str]:
    path = root / "journal" / "days" / today.isoformat() / "decision.json"
    if not path.exists():
        return ["no decision.json for today"]
    rec = json.loads(path.read_text(encoding="utf-8"))
    d = rec.get("decision", {})
    lines = [
        f"{d.get('regime', '?')} | debate: {d.get('debate_winner', '?')}",
        str(d.get("bias", "")),
        *_forecasts(d.get("forecasts", [])),
    ]
    res = rec.get("resolution", [])
    if res:
        for r in res:
            idea = r.get("idea", {})
            lines.append(
                f"idea {r.get('n', 0) + 1}: {idea.get('structure', '?')} "
                f"{idea.get('underlying', '?')} -> {r.get('status', '?')} ({r.get('reason', '')})"
            )
    else:
        lines.append("ideas: none")
    if rec.get("closed_by_trader"):
        lines.append("closed by trader: " + ", ".join(rec["closed_by_trader"]))
    lines += [f"problem: {p}" for p in rec.get("problems", [])]
    thesis = str(d.get("thesis", ""))
    if thesis:
        lines.append("thesis: " + (thesis if len(thesis) <= 400 else thesis[:397] + "..."))
    summary = root / "journal" / "summary.json"
    if summary.exists():
        s = json.loads(summary.read_text(encoding="utf-8"))
        for row in s.get("forecasts", []):
            if row.get("group") == "all" and row.get("n"):
                lines.append(
                    f"score {row['horizon']}d: hit {row['hit_rate']:.0%} vs always-up "
                    f"{row['always_up_hit_rate']:.0%} (n={row['n']})"
                )
    return lines


def build(job: str, today: date, root: Path, segments: dict[str, str]) -> tuple[str, str] | None:
    """(title, body) for a finished job, or None for jobs without a digest.

    `segments` maps step name -> the log text that step wrote during this run."""
    if job not in DIGEST_JOBS:
        return None
    parts: list[str] = []
    if job == "journal":
        parts += journal_lines(root, today)
    for step, text in segments.items():
        if job == "journal" and step == "journal":
            continue  # decision.json already says it better
        lines = key_lines(text)
        if lines:
            parts.append(f"[{step}]")
            parts += lines
    body = "\n".join(parts) if parts else "done, nothing to report"
    return f"{DIGEST_JOBS[job]} {today}", body
