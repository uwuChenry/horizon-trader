"""Forward tests and paper accounts: ledgers under data/live, IBKR observations, job health.

Read-only: nothing here talks to a broker or places an order.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from fastapi import APIRouter

from horizon_trader import config
from horizon_trader.backtest import analytics as A
from horizon_trader.dashboard.serialize import clean, points, table

router = APIRouter(prefix="/api/live")


def business_days_between(a: date, b: date) -> int:
    """Weekdays strictly after a up to and including b (holidays not excluded)."""
    if b <= a:
        return 0
    return int(len(pd.bdate_range(a + timedelta(days=1), b)))


def last_close(symbol: str) -> float | None:
    path = config.data_dir() / "bars" / f"{symbol}.parquet"
    if not path.exists():
        return None
    try:
        return float(pd.read_parquet(path, columns=["close"])["close"].dropna().iloc[-1])
    except (OSError, IndexError, KeyError, ValueError):
        return None


def benchmark(symbol: str, index: pd.DatetimeIndex, start_equity: float) -> pd.Series | None:
    path = config.data_dir() / "bars" / f"{symbol}.parquet"
    if not path.exists() or not len(index):
        return None
    close = pd.read_parquet(path, columns=["close"])["close"]
    close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
    b = close.reindex(index).ffill().dropna()
    return b / b.iloc[0] * start_equity if len(b) else None


IDEA_COLS = ["id", "date", "underlying", "structure", "confidence", "status", "qty", "limit",
             "cost", "quote_source", "reason", "close_reason"]  # fmt: skip


def is_option(symbol: str) -> bool:
    """OCC-style option symbol (ROOT + YYMMDD + C/P + 8-digit strike), e.g. SPY261218C00770000."""
    s = symbol
    return len(s) >= 16 and s[-9] in "CP" and s[-8:].isdigit() and s[-15:-9].isdigit()


def ledger(folder: Path) -> dict:
    eq = pd.read_csv(folder / "equity.csv", parse_dates=["date"]).set_index("date")["equity"]
    state = (
        json.loads((folder / "state.json").read_text(encoding="utf-8"))
        if (folder / "state.json").exists()
        else {}
    )
    fills = pd.read_csv(folder / "fills.csv") if (folder / "fills.csv").exists() else None
    positions = []
    for symbol, qty in (state.get("holdings") or {}).items():
        option = is_option(symbol)
        px = None if option else last_close(symbol)
        positions.append({"symbol": symbol, "shares": qty, "price": px,
                          "unit": "contracts" if option else "shares",
                          "value": qty * px if px is not None else None})  # fmt: skip
    total = eq.iloc[-1] if len(eq) else None
    for p in positions:
        p["weight"] = p["value"] / total if p["value"] is not None and total else None
    positions.sort(key=lambda p: -(p["value"] or 0))
    name = folder.name
    kind = "shadow" if name.endswith("_shadow") else "paper" if name.endswith("_paper") else "live"
    stats = A.equity_stats(eq) if len(eq) > 2 else {}
    out = {
        "name": name,
        "kind": kind,
        "start": eq.index[0].strftime("%Y-%m-%d") if len(eq) else None,
        "end": eq.index[-1].strftime("%Y-%m-%d") if len(eq) else None,
        "start_equity": float(eq.iloc[0]) if len(eq) else None,
        "equity_now": float(total) if total is not None else None,
        "return": float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) else None,
        "max_dd": stats.get("max DD"),
        "days": int(len(eq)),
        "cash": state.get("cash"),
        "equity": points(eq),
        "benchmark": points(benchmark("SPY", pd.DatetimeIndex(eq.index), float(eq.iloc[0])))
        if len(eq)
        else [],
        "positions": positions,
        "pending": state.get("pending", []),
        "fills": None,
        "commissions": None,
    }
    for pin in ("follow.json", "alpaca_account.json"):  # Alpaca ledgers record their account
        if (folder / pin).exists():
            out["account"] = json.loads((folder / pin).read_text(encoding="utf-8")).get("account")
    if (folder / "follow.json").exists():  # the AI competition follower's idea log
        records = json.loads((folder / "follow.json").read_text(encoding="utf-8"))["records"]
        ideas = pd.DataFrame(
            [{c: r.get(c) for c in IDEA_COLS} for r in records.values()], columns=IDEA_COLS
        )
        out["ideas"] = table(ideas.sort_values("id", ascending=False)) if len(ideas) else None
    if fills is not None and len(fills):
        recent = fills.iloc[::-1].head(200)
        out["fills"] = table(recent)
        out["commissions"] = {
            "actual": float(pd.to_numeric(fills["commission"], errors="coerce").sum()),
            "modeled": float(pd.to_numeric(fills["modeled_commission"], errors="coerce").sum()),
            "orders": int(len(fills)),
        }
    return out


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


def health(today: date | None = None) -> list[dict]:
    today = today or datetime.now().date()
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
    if (data / "journal").exists():  # missing day: Codex login expired?
        days = [d for d in (data / "journal" / "days").glob("????-??-??")
                if (d / "decision.json").exists()]  # fmt: skip
        out.append(check("Forecast journal (15:00, Codex login)", _latest_stem(days), today, 1,
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
    return out


@router.get("")
def live() -> dict:
    root = config.data_dir() / "live"
    ledgers = []
    for folder in sorted(p.parent for p in root.glob("*/equity.csv")):
        try:
            ledgers.append(ledger(folder))
        except (OSError, ValueError, KeyError) as exc:
            ledgers.append({"name": folder.name, "error": str(exc)})
    return clean(
        {
            "ledgers": ledgers,
            "health": health(),
            "observations": observations(),
            "kill_switch": (root / "KILL").exists(),
        }
    )
