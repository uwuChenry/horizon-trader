"""Forward tests and paper accounts: ledgers under data/live, IBKR observations, job health.

Read-only: nothing here talks to a broker or places an order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter

from horizon_trader import config
from horizon_trader.backtest import analytics as A
from horizon_trader.dashboard.serialize import clean, points, table
from horizon_trader.ops.health import health, observations

router = APIRouter(prefix="/api/live")


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
