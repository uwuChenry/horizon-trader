"""The forecast journal (agents/journal.py): daily briefs, the debate, forecasts and the
hypothetical book with its mirror controls. Reads files only; scoring happens in the job."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

from horizon_trader import config
from horizon_trader.dashboard.serialize import clean, points, table

router = APIRouter(prefix="/api/journal")
ROLES = ["market", "news", "earnings", "bull", "bear", "bull_rebuttal", "bear_rebuttal"]


def _root() -> Path:
    return config.data_dir() / "journal"


def _json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _days() -> list[dict]:
    out = []
    for d in sorted((_root() / "days").glob("????-??-??"), reverse=True):
        rec = _json(d / "decision.json")
        if rec is None:
            out.append({"date": d.name, "complete": False})
            continue
        dec = rec["decision"]
        out.append({
            "date": d.name, "complete": True, "regime": dec["regime"], "bias": dec["bias"],
            "thesis": dec["thesis"], "invalidation": dec["invalidation"],
            "debate_winner": dec["debate_winner"],
            "opened": sum(r["status"] == "opened" for r in rec["resolution"]),
            "proposed": sum(r["idea"]["structure"] != "none" for r in rec["resolution"]),
            "problems": rec["problems"],
        })  # fmt: skip
    return out


POSITION_COLS = [
    "id", "kind", "date", "underlying", "structure", "contracts", "qty", "entry_cost",
    "last_value", "exit_planned", "status", "exit_date", "exit_reason", "pnl", "confidence",
    "thesis", "invalidation",
]  # fmt: skip


def _positions() -> pd.DataFrame:
    book = _json(_root() / "book.json")
    rows = []
    for p in (book or {}).get("positions", []):
        legs = " / ".join(
            f"{'+' if leg['side'] > 0 else '-'}{leg['symbol']}"
            + (f" ({leg['quote_source']})" if leg.get("quote_source") else "")
            for leg in p.get("legs", [])
        )  # quote_source: ibkr (live) or yahoo (~15 min delayed)
        rows.append({**{c: p.get(c) for c in POSITION_COLS}, "contracts": legs})
    df = pd.DataFrame(rows, columns=POSITION_COLS)
    return df.sort_values(["date", "id"], ascending=[False, True]) if len(df) else df


@router.get("")
def journal() -> dict:
    root = _root()
    eq_path = config.data_dir() / "live" / "journal_shadow" / "equity.csv"
    equity = (
        pd.read_csv(eq_path, parse_dates=["date"]).set_index("date")["equity"]
        if eq_path.exists()
        else None
    )
    fc_path = root / "scored_forecasts.csv"
    forecasts = (
        pd.read_csv(fc_path, dtype={"date": str, "benchmark": str}, keep_default_na=False)
        if fc_path.exists()
        else pd.DataFrame()
    )
    if len(forecasts):
        forecasts = forecasts.sort_values(["date", "ticker"], ascending=[False, True])
        forecasts = forecasts.drop(columns=[c for c in ("prompt_sha", "model") if c in forecasts])
        for c in ("ret", "bench_ret", "edge", "hit"):
            forecasts[c] = pd.to_numeric(forecasts[c], errors="coerce")
    return clean({
        "exists": root.exists(),
        "summary": _json(root / "summary.json"),
        "days": _days(),
        "positions": table(_positions()),
        "forecasts": table(forecasts, limit=500) if len(forecasts) else None,
        "equity": points(equity),
    })  # fmt: skip


@router.get("/{day}")
def day(day: str) -> dict:
    folder = _root() / "days" / day
    if not day.replace("-", "").isdigit() or not folder.is_dir():
        raise HTTPException(404, f"no journal day {day}")
    reports = {}
    for role in ROLES:
        p = folder / "reports" / f"{role}.md"
        if p.exists():
            reports[role] = p.read_text(encoding="utf-8")
    meta = {}
    for role in [*ROLES, "trader"]:
        raw = _json(folder / "raw" / f"{role}.json")
        if raw:
            w = raw.get("wrapper", {})
            meta[role] = {
                "model": raw.get("model"), "tools": raw.get("tools"),
                "started": raw.get("started"), "finished": raw.get("finished"),
                "cost_usd": w.get("total_cost_usd"), "turns": w.get("num_turns"),
            }  # fmt: skip
    packet = folder / "packet.md"
    return clean({
        "date": day,
        "record": _json(folder / "decision.json"),
        "packet": packet.read_text(encoding="utf-8") if packet.exists() else None,
        "reports": reports,
        "meta": meta,
    })  # fmt: skip
