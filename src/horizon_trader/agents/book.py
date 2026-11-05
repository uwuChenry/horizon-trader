"""The journal's hypothetical book: turn trade specs into priced positions, enforce the risk
rules, mark positions to live quotes, and score forecasts and positions.

Pricing is deliberately conservative: options are bought at the ask and sold at the bid
(spreads pay ask - bid on the way in and bid - ask on the way out), plus a per-contract fee.
Every idea gets a **mirror** opened at the same moment in the opposite direction (put <-> call,
long shares <-> short shares) and sized by the same rule. The mirror is the control: if the
ideas only beat their mirrors by chance, the timing/direction carried no information and any
profit came from the option structure itself.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader.agents.market import Market, live, nearest_expiry, requote


@dataclass(frozen=True)
class Rules:
    account: float = 10_000.0
    premium_cap: float = 150.0  # option premium per idea
    premium_total: float = 600.0  # option premium across open ideas
    shares_cap: float = 2_500.0  # notional per shares idea
    max_new: int = 3
    max_open: int = 8
    fee_per_contract: float = 0.65  # assumption: IBKR Pro list price; Alpaca charges less
    stock_fee: float = 1.0  # assumption per stock order
    stock_slip: float = 0.0002  # 2 bp against us per stock fill
    max_quote_spread: float = 0.30  # reject legs whose (ask - bid) / mid exceeds this


MIRROR = {
    "long_call": "long_put", "long_put": "long_call",
    "call_debit_spread": "put_debit_spread", "put_debit_spread": "call_debit_spread",
    "shares_long": "shares_short",
}  # fmt: skip


def exit_date(today: str, horizon_days: int, expiry: str | None = None) -> str:
    """Planned close: `horizon_days` weekdays after today (holidays not excluded), or expiry."""
    d = pd.Timestamp(today) + pd.offsets.BDay(horizon_days)
    if expiry is not None:
        d = min(d, pd.Timestamp(expiry))
    return d.strftime("%Y-%m-%d")


def _pick(book: pd.DataFrame, target: float) -> pd.Series:
    return book.iloc[(book["strike"] - target).abs().argmin()]


def resolve(
    idea: dict, market: Market, today: str, rules: Rules, budget: float, pid: str, kind: str
) -> tuple[dict | None, str]:
    """A priced position for `idea`, or (None, reason it was rejected)."""
    structure, u = idea["structure"], idea["underlying"].upper().strip()
    if structure not in {*MIRROR, "shares_short"}:
        return None, f"structure {structure!r} not tradeable"
    spot = market.spot(u)
    base = {
        "id": pid, "kind": kind, "date": today, "underlying": u, "structure": structure,
        "spec": {k: idea.get(k) for k in ("days_to_expiry", "otm_pct", "spread_width_pct",
                                          "horizon_days")},
        "confidence": idea.get("confidence"), "thesis": idea.get("thesis", ""),
        "invalidation": idea.get("invalidation", ""), "spot": spot, "status": "open",
    }  # fmt: skip
    if structure.startswith("shares"):
        side = 1 if structure == "shares_long" else -1
        px = spot * (1 + side * rules.stock_slip)
        qty = math.floor(min(budget, rules.shares_cap) / px)
        if qty < 1:
            return None, f"one share ({px:,.2f}) exceeds the budget"
        legs = [{"type": "stock", "symbol": u, "side": side}]
        return base | {
            "legs": legs, "qty": qty, "unit_entry": px, "expiry": None,
            "entry_cost": side * qty * px + rules.stock_fee,
            "exit_planned": exit_date(today, idea["horizon_days"]),
        }, "ok"  # fmt: skip

    expiry = nearest_expiry(market.expiries(u), today, idea["days_to_expiry"])
    if expiry is None:
        return None, f"no listed options for {u}"
    calls, puts = market.chain(u, expiry)
    call = structure.startswith(("long_call", "call"))
    book, right = (calls, "C") if call else (puts, "P")
    sign = 1 if call else -1
    long_row = _pick(book, spot * (1 + sign * idea["otm_pct"] / 100))
    rows = [(long_row, 1)]
    if "spread" in structure:
        width = max(idea.get("spread_width_pct") or 0, 1.0) / 100 * spot
        beyond = book[(book["strike"] - long_row["strike"]) * sign > 0]
        if beyond.empty:
            return None, "no strike beyond the long leg for the spread"
        rows.append((_pick(beyond, long_row["strike"] + sign * width), -1))
    fresh = requote(market, pd.DataFrame([r for r, _ in rows]))  # live bid/ask when available
    rows = [(fresh.iloc[j], s) for j, (_, s) in enumerate(rows)]
    for row, _ in rows:
        if not live(row):
            return None, f"no live quote for {row['contractSymbol']} (market closed?)"
        mid = (row["bid"] + row["ask"]) / 2
        if (row["ask"] - row["bid"]) / mid > rules.max_quote_spread:
            return None, f"quote too wide on {row['contractSymbol']} ({row['bid']}/{row['ask']})"
    debit = sum(r["ask"] if s > 0 else -r["bid"] for r, s in rows)
    if debit <= 0:
        return None, "spread has no debit at current quotes"
    qty = math.floor(budget / (debit * 100))
    if qty < 1:
        return None, f"one contract costs ${debit * 100:,.0f}, above the ${budget:,.0f} budget"
    legs = [
        {"type": "option", "symbol": r["contractSymbol"], "expiry": expiry,
         "strike": float(r["strike"]), "right": right, "side": s,
         "bid": float(r["bid"]), "ask": float(r["ask"]),
         "iv": float(r.get("impliedVolatility", np.nan)),
         "quote_source": r.get("quote_source", "yahoo")}
        for r, s in rows
    ]  # fmt: skip
    return base | {
        "legs": legs, "qty": qty, "unit_entry": debit, "expiry": expiry,
        "entry_cost": qty * debit * 100 + rules.fee_per_contract * qty * len(legs),
        "exit_planned": exit_date(today, idea["horizon_days"], expiry),
    }, "ok"  # fmt: skip


def premium_open(positions: list[dict]) -> float:
    return sum(
        p["entry_cost"] for p in positions
        if p["status"] == "open" and p["kind"] == "idea" and p["expiry"] is not None
    )  # fmt: skip


def open_ideas(positions: list[dict]) -> list[dict]:
    return [p for p in positions if p["status"] == "open" and p["kind"] == "idea"]


def open_ideas_with_mirrors(
    ideas: list[dict], market: Market, today: str, rules: Rules, positions: list[dict]
) -> list[dict]:
    """Price and risk-check the trader's ideas; returns one record per idea (incl. rejected)."""
    out = []
    n_open = len(open_ideas(positions))
    for i, idea in enumerate(ideas):
        rec = {"n": i, "idea": idea, "status": "rejected", "reason": "", "id": None}
        out.append(rec)
        if idea["structure"] == "none":
            rec["reason"] = "no trade"
            continue
        if i >= rules.max_new:
            rec["reason"] = f"more than {rules.max_new} new ideas today"
            continue
        if n_open >= rules.max_open:
            rec["reason"] = f"{rules.max_open} ideas already open"
            continue
        option = not idea["structure"].startswith("shares")
        budget = (
            min(rules.premium_cap, rules.premium_total - premium_open(positions))
            if option
            else rules.shares_cap
        )
        if budget <= 0:
            rec["reason"] = "total premium cap reached"
            continue
        pid = f"{today}-{i + 1}"
        try:
            pos, why = resolve(idea, market, today, rules, budget, pid, "idea")
        except Exception as exc:  # noqa: BLE001 - a bad ticker rejects one idea, not the run
            pos, why = None, f"pricing failed: {exc}"
        if pos is None:
            rec["reason"] = why
            continue
        positions.append(pos)
        n_open += 1
        rec |= {"status": "opened", "reason": "ok", "id": pid}
        twin = idea | {"structure": MIRROR[idea["structure"]]}
        try:
            m, why = resolve(twin, market, today, rules, budget, f"{pid}-m", "mirror")
        except Exception as exc:  # noqa: BLE001
            m, why = None, f"pricing failed: {exc}"
        if m is not None:
            m["parent"] = pid
            pos["mirror"] = m["id"]
            positions.append(m)
        rec["mirror"] = m["id"] if m else f"not priced: {why}"
    return out


# ---------- marking and closing ----------


def mark(pos: dict, market: Market, rules: Rules) -> float | None:
    """What closing now would bring in (long legs at the bid, short legs at the ask)."""
    if pos["legs"][0]["type"] == "stock":
        side = pos["legs"][0]["side"]
        px = market.spot(pos["underlying"]) * (1 - side * rules.stock_slip)
        return side * pos["qty"] * px
    calls, puts = market.chain(pos["underlying"], pos["expiry"])
    rows = []
    for leg in pos["legs"]:
        book = calls if leg["right"] == "C" else puts
        row = book[book["contractSymbol"] == leg["symbol"]]
        if row.empty:
            return None
        rows.append(row.iloc[0])
    fresh = requote(market, pd.DataFrame(rows))
    unit = 0.0
    for leg, (_, row) in zip(pos["legs"], fresh.iterrows(), strict=True):
        if not live(row):
            return None
        unit += row["bid"] if leg["side"] > 0 else -row["ask"]
    return max(unit, 0.0) * 100 * pos["qty"]


def settle(pos: dict, market: Market) -> float | None:
    """Value at expiry from the underlying's unadjusted close that day."""
    s = market.raw_close(pos["underlying"], pos["expiry"])
    if s is None:
        return None
    unit = sum(
        leg["side"] * max(0.0, (s - leg["strike"]) if leg["right"] == "C" else (leg["strike"] - s))
        for leg in pos["legs"]
    )
    return max(unit, 0.0) * 100 * pos["qty"]


def close(pos: dict, value: float, today: str, reason: str, rules: Rules) -> None:
    stock = pos["legs"][0]["type"] == "stock"
    fee = rules.stock_fee if stock else rules.fee_per_contract * pos["qty"] * len(pos["legs"])
    if not stock and (reason == "expired" or value <= 0):
        fee = 0.0  # worthless or exercised/settled at expiry: no closing order
    pos |= {
        "status": "closed", "exit_date": today, "exit_reason": reason, "exit_value": value,
        "exit_fee": fee, "pnl": value - pos["entry_cost"] - fee,
    }  # fmt: skip


def step(
    positions: list[dict], market: Market, today: str, rules: Rules, close_ids=()
) -> list[dict]:
    """Mark every open position; close those past their horizon/expiry or named by the trader.
    Returns today's marks [{date, id, value}]."""
    marks = []
    t = pd.Timestamp(today)
    for pos in positions:
        if pos["status"] != "open":
            continue
        expired = pos["expiry"] is not None and pd.Timestamp(pos["expiry"]) < t
        try:
            value = settle(pos, market) if expired else mark(pos, market, rules)
        except Exception:  # noqa: BLE001 - leave it open, try again next run
            value = None
        if value is None:
            continue
        marks.append({"date": today, "id": pos["id"], "value": value})
        parent_closed = pos.get("parent") in close_ids
        if expired:
            close(pos, value, today, "expired", rules)
        elif pos["id"] in close_ids or parent_closed:
            close(pos, value, today, "trader", rules)
        elif t >= pd.Timestamp(pos["exit_planned"]):
            reason = "expiry" if pos["expiry"] == today else "horizon"
            close(pos, value, today, reason, rules)
    return marks


# ---------- storage ----------


def load(root: Path) -> list[dict]:
    path = root / "book.json"
    return json.loads(path.read_text(encoding="utf-8"))["positions"] if path.exists() else []


def save(root: Path, positions: list[dict], marks: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / "book.json.tmp"
    tmp.write_text(json.dumps({"positions": positions}, indent=1, default=float), "utf-8")
    tmp.replace(root / "book.json")
    if marks:
        path = root / "marks.csv"
        new = pd.DataFrame(marks)
        if path.exists():
            old = pd.read_csv(path, dtype={"date": str, "id": str})
            new = pd.concat([old, new]).drop_duplicates(["date", "id"], keep="last")
        new.to_csv(path, index=False)


def equity_curve(positions: list[dict], marks: pd.DataFrame, rules: Rules) -> pd.DataFrame:
    """Daily hypothetical equity of the ideas (not the mirrors): account + realized P&L +
    open positions at their last mark."""
    ideas = [p for p in positions if p["kind"] == "idea"]
    dates = sorted({p["date"] for p in ideas} | set(marks.get("date", pd.Series(dtype=str))))
    rows = []
    for d in dates:
        realized = sum(p["pnl"] for p in ideas if p["status"] == "closed" and p["exit_date"] <= d)
        unreal, invested = 0.0, 0.0
        for p in ideas:
            if p["date"] > d or (p["status"] == "closed" and p["exit_date"] <= d):
                continue
            m = marks[(marks["id"] == p["id"]) & (marks["date"] <= d)] if len(marks) else marks
            value = float(m["value"].iloc[-1]) if len(m) else p["entry_cost"]
            unreal += value - p["entry_cost"]
            invested += p["entry_cost"]
        equity = rules.account + realized + unreal
        rows.append({"date": d, "equity": equity, "cash": rules.account + realized - invested})
    return pd.DataFrame(rows, columns=["date", "equity", "cash"])


# ---------- scoring ----------


def score_forecasts(fc: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """Each forecast against the close `horizon_days` trading days after its date."""
    out = fc.copy()
    for col in ("exit_date", "ret", "bench_ret", "edge", "hit"):
        out[col] = np.nan if col != "exit_date" else None
    for i, f in out.iterrows():
        t = f["ticker"]
        if t not in closes:
            continue
        s = closes[t].dropna()
        d = pd.Timestamp(f["date"])
        if d not in s.index:
            continue
        j = s.index.get_loc(d) + int(f["horizon_days"])
        if j >= len(s):
            continue
        ret = s.iloc[j] / s.loc[d] - 1
        bench = 0.0
        if f.get("benchmark") == "SPY" and "SPY" in closes:
            b = closes["SPY"].dropna()
            bench = b.loc[s.index[j]] / b.loc[d] - 1 if d in b.index and s.index[j] in b else np.nan
        sign = 1 if f["direction"] == "up" else -1
        excess = ret - bench
        out.loc[i, ["ret", "bench_ret", "edge", "hit"]] = [
            ret,
            bench,
            sign * excess,
            float(sign * excess > 0),
        ]
        out.loc[i, "exit_date"] = s.index[j].strftime("%Y-%m-%d")
    return out


def _t(x: pd.Series) -> float | None:
    x = x.dropna()
    if len(x) < 3 or x.std() == 0:
        return None
    return float(x.mean() / (x.std() / np.sqrt(len(x))))


def summary(scored: pd.DataFrame, positions: list[dict]) -> dict:
    """Headline numbers for the dashboard and the protocol's pass/fail rules."""
    out: dict = {"forecasts": [], "by_confidence": [], "ideas": {}}
    done = scored.dropna(subset=["hit"]) if len(scored) else scored
    for h in (1, 5, 20):
        for group, sub in (("SPY+QQQ (mandatory)", done[done["mandatory"]]), ("all", done)):
            sub = sub[sub["horizon_days"] == h]
            # Non-overlapping subsample for the t-stat: every h-th forecast per ticker.
            nonover = pd.concat(
                [g.sort_values("date").iloc[::h] for _, g in sub.groupby(["ticker", "benchmark"])]
            ) if len(sub) else sub  # fmt: skip
            excess = sub["ret"] - sub["bench_ret"]
            out["forecasts"].append({
                "horizon": h, "group": group, "n": int(len(sub)),
                "hit_rate": float(sub["hit"].mean()) if len(sub) else None,
                "always_up_hit_rate": float((excess > 0).mean()) if len(sub) else None,
                "mean_edge_pct": float(sub["edge"].mean() * 100) if len(sub) else None,
                "t_nonoverlap": _t(nonover["edge"]) if len(nonover) else None,
                "n_nonoverlap": int(len(nonover)),
            })  # fmt: skip
    for c, sub in done.groupby("confidence") if len(done) else []:
        out["by_confidence"].append(
            {"confidence": int(c), "n": int(len(sub)), "hit_rate": float(sub["hit"].mean())}
        )
    ideas = [p for p in positions if p["kind"] == "idea"]
    closed = [p for p in ideas if p["status"] == "closed"]
    by_id = {p["id"]: p for p in positions}
    paired = [(p, by_id.get(p.get("mirror"))) for p in closed]
    paired = [(p, m) for p, m in paired if m is not None and m["status"] == "closed"]
    out["ideas"] = {
        "opened": len(ideas), "open": len(ideas) - len(closed), "closed": len(closed),
        "pnl": float(sum(p["pnl"] for p in closed)),
        "win_rate": float(np.mean([p["pnl"] > 0 for p in closed])) if closed else None,
        "paired": len(paired),
        "pnl_paired": float(sum(p["pnl"] for p, _ in paired)),
        "mirror_pnl_paired": float(sum(m["pnl"] for _, m in paired)),
        "t_vs_mirror": _t(pd.Series([p["pnl"] - m["pnl"] for p, m in paired], dtype=float)),
    }  # fmt: skip
    return out


def rules_dict(rules: Rules) -> dict:
    return asdict(rules)
