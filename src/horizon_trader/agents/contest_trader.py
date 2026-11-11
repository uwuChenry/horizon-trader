"""AI contest trader: an LLM (GPT-6 Astra via `codex exec`) runs the Alpaca competition PAPER
account by itself. Replaces the journal follower (`agents/competition.py`), which never traded
because the journal's protocol makes "no new trade" the normal answer.

    uv run python -m horizon_trader.agents.contest_trader run [--dry-run]  # one session (13:30 ET)
    uv run python -m horizon_trader.agents.contest_trader sync             # book fills (18:00)
    uv run python -m horizon_trader.agents.contest_trader status
    uv run python -m horizon_trader.agents.contest_trader kill             # KILL file + cancel

The LLM only decides; code builds every number it sees and checks every order it gives.
A session:
1. Guards: kill switch, paper keys, the same Alpaca account as before (pinned in follow.json).
2. Sync: book our finished orders into fills.csv; place the broker stop for newly filled shares.
3. Mechanical exits (code, no LLM): contest end, option expiry eve, exit_by reached, an option's
   underlying stop or target crossed, a shares target reached (shares stops sit at the broker).
4. Briefing: account, positions with live marks, track record, the model's own notebook and
   recent session summaries, the journal's market packet, a scan table of ~70 liquid names.
5. Research call (web search): position reviews + 0-4 candidates.
6. Code builds option ladders (Yahoo chains, live IBKR bid/ask first) and share quotes for them.
7. Decision call (no tools): position actions, orders naming ladder contracts, a rewritten
   notebook (its only memory) and a session summary.
8. Risk checks resize or reject each order (`check_order`); rejections go into the next
   briefing so the model learns the limits. Then closes, updates, opens.
Everything (briefing, prompts, raw answers, ladders, checks, orders) is saved under
data/live/competition_ai_paper/sessions/<date>_<HHMM>/.

Paper fills are simulated and ~7 weeks of one model says nothing about skill: this is a contest
entry and a harness test (research/competition/README.md, "AI contest trader").
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from horizon_trader import config
from horizon_trader.agents import contest_prompts as P
from horizon_trader.agents.competition import (
    GuardError,
    _append_fills,
    kill_switch_path,
    prev_weekday,
    tick_up,
)
from horizon_trader.execution.alpaca_broker import NY, Leg, OrderInfo, OrderSpec

log = logging.getLogger(__name__)

LEDGER = "competition_ai_paper"  # same folder (and dashboard ledger) as the follower
PREFIX = "contest"  # client_order_id prefix
MODEL, EFFORT = "gpt-6-astra", "high"
OPEN_STATES = {"opening", "open", "closing"}

# Liquid names for the scan table. The model may also pick other liquid US names.
UNIVERSE = (
    "SPY QQQ IWM DIA SMH SOXX XLK XLF XLE XLV XLI XLY XLP XLU XLB XLC XBI KRE ARKK GLD SLV TLT "
    "USO IBIT TQQQ SOXL "
    "AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD MU INTC QCOM ARM TSM ASML LRCX AMAT KLAC MRVL "
    "SMCI DELL ORCL CRM ADBE NOW SNOW PLTR NFLX UBER SHOP COIN MSTR HOOD JPM GS BAC V MA "
    "LLY UNH NVO XOM CVX CAT BA GE WMT COST HD NKE DIS SBUX"
).split()


@dataclass(frozen=True)
class Rules:
    max_positions: int = 6
    max_new: int = 3  # new positions per session
    max_candidates: int = 4
    shares_idea_pct: float = 0.40  # of equity, per shares position
    shares_total_pct: float = 1.00  # all shares positions: no margin
    option_idea_pct: float = 0.20  # premium per option position
    option_total_pct: float = 0.50  # all open option premium
    max_stop_pct: float = 0.15  # a shares stop at most 15% below the entry
    min_price: float = 5.0
    min_dollar_volume: float = 50e6  # 20-day average
    max_stock_spread: float = 0.01  # IEX quotes can be thin
    max_option_spread: float = 0.25  # (ask - bid) / mid
    min_open_interest: int = 100
    min_premium: float = 0.20
    stock_pad: float = 0.002  # stock buy limit = ask * (1 + pad)
    last_open: str = "2026-12-23"
    close_all_from: str = "2026-12-28"
    open_cutoff: str = "15:50"  # ET
    first_equity: tuple[float, float] = (1_000.0, 10_000.0)
    ladder_days: tuple[int, ...] = (14, 35, 63)  # target days to expiry of the ladder's expiries
    ladder_strikes: int = 7

    def limits_text(self, equity: float, used: dict) -> str:
        e = equity
        return "\n".join([
            f"- At most {self.max_positions} open positions, one per underlying; at most "
            f"{self.max_new} new positions per session.",
            f"- Shares: at most {self.shares_idea_pct:.0%} of equity per position "
            f"(${self.shares_idea_pct * e:,.0f}); all shares together at most "
            f"{self.shares_total_pct:.0%} (${self.shares_total_pct * e:,.0f}, "
            f"${used['shares']:,.0f} used). No margin. Stop at most "
            f"{self.max_stop_pct:.0%} below the entry; the stop sits at the broker as a GTC order.",
            f"- Options: premium at most {self.option_idea_pct:.0%} of equity per position "
            f"(${self.option_idea_pct * e:,.0f}); all premium together at most "
            f"{self.option_total_pct:.0%} (${self.option_total_pct * e:,.0f}, "
            f"${used['options']:,.0f} used). Bid/ask spread at most "
            f"{self.max_option_spread:.0%} of mid, open interest at least "
            f"{self.min_open_interest}. Option stops/targets are checked against the underlying "
            "once per session, so they're not instant.",
            f"- Stocks: price above ${self.min_price:.0f}, over "
            f"${self.min_dollar_volume / 1e6:.0f}M traded per day on average.",
            "- Orders too big are cut to the limit; anything else that breaks a rule is rejected.",
        ])  # fmt: skip


# ---------------------------------------------------------------- storage


def folder(root: Path | None = None) -> Path:
    return (root or config.data_dir() / "live") / LEDGER


def load_state(root: Path | None = None) -> dict:
    path = folder(root) / "trader.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    state = {"account": None, "start": None, "notebook": "", "positions": {}, "sessions": [],
             "rejected": [], "seq": 0}  # fmt: skip
    follow = folder(root) / "follow.json"  # the follower pinned the account on 2026-11-05
    if follow.exists():
        state["account"] = json.loads(follow.read_text(encoding="utf-8")).get("account")
    return state


def save_state(state: dict, root: Path | None = None) -> None:
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "trader.json.tmp"
    tmp.write_text(json.dumps(state, indent=1, default=float), encoding="utf-8")
    tmp.replace(d / "trader.json")


def write_ledger_files(acct: dict, positions: dict, state: dict, today: str, root) -> None:
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "equity.csv"
    row = pd.DataFrame([{"date": today, "equity": acct["equity"], "cash": acct["cash"]}])
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str})
        row = pd.concat([old[old["date"] != today], row], ignore_index=True)
    row.to_csv(path, index=False)
    pending = [
        {"symbol": p["symbol"], "quantity": p["qty"], "ref_price": p.get("limit"),
         "asof": p["opened"]}
        for p in state["positions"].values() if p["status"] == "opening"
    ]  # fmt: skip
    st = {"cash": acct["cash"], "holdings": positions, "pending": pending}
    (d / "state.json").write_text(json.dumps(st, indent=2), encoding="utf-8")


class SessionLog:
    def __init__(self, root: Path | None, stamp: str, dry_run: bool):
        self.dir = folder(root) / "sessions" / (stamp + ("_dry" if dry_run else ""))
        self.dir.mkdir(parents=True, exist_ok=True)

    def text(self, name: str, body: str) -> None:
        (self.dir / name).write_text(body, encoding="utf-8")

    def json(self, name: str, obj) -> None:
        self.text(name, json.dumps(obj, indent=1, default=str))


# ---------------------------------------------------------------- indicators and scan


def rsi(close: pd.Series, n: int) -> float:
    """Wilder's RSI of the last bar."""
    d = close.diff().dropna()
    if len(d) < n:
        return float("nan")
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    down = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean().iloc[-1]
    if down == 0:
        return 100.0
    return float(100 - 100 / (1 + up / down))


def atr_pct(bars: pd.DataFrame, n: int = 14) -> float:
    h, lo, c = bars["High"], bars["Low"], bars["Close"]
    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    return float(tr.tail(n).mean() / c.iloc[-1] * 100)


def scan_row(bars: pd.DataFrame) -> dict | None:
    b = bars.dropna(subset=["Close"])
    if len(b) < 61:
        return None
    c = b["Close"]
    last = c.iloc[-1]

    def ret(n):
        return (last / c.iloc[-1 - n] - 1) * 100

    return {
        "last": last, "1d %": ret(1), "5d %": ret(5), "20d %": ret(20), "60d %": ret(60),
        "RSI2": rsi(c.tail(60), 2), "RSI14": rsi(c.tail(120), 14),
        "vs 20d %": (last / c.tail(20).mean() - 1) * 100,
        "vs 50d %": (last / c.tail(50).mean() - 1) * 100,
        "ATR %": atr_pct(b), "off 20d hi %": (last / b["High"].tail(20).max() - 1) * 100,
        "off 52w hi %": (last / b["High"].tail(252).max() - 1) * 100,
        "$vol 20d M": float((c * b["Volume"]).tail(20).mean() / 1e6),
    }  # fmt: skip


def scan_table(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = {t: r for t, df in bars.items() if (r := scan_row(df)) is not None}
    return pd.DataFrame(rows).T.sort_values("20d %", ascending=False)


class YahooBars:
    """Daily OHLCV from yfinance (dividend-adjusted). Prototype source, like the journal's."""

    def __init__(self) -> None:
        import yfinance as yf

        yf.set_tz_cache_location(str(config.data_dir() / "yfinance-cache"))
        self.yf = yf

    def bars(self, symbols: list[str], days: int = 400) -> dict[str, pd.DataFrame]:
        raw = self.yf.download(sorted(set(symbols)), period=f"{days}d", auto_adjust=True,
                               group_by="ticker", progress=False, threads=True)  # fmt: skip
        out = {}
        for s in set(symbols):
            try:
                df = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            df = df.dropna(how="all")
            if len(df):
                df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
                out[s] = df
        return out

    def earnings_date(self, symbol: str) -> str:
        try:
            cal = self.yf.Ticker(symbol).calendar or {}
            dates = [pd.Timestamp(x) for x in cal.get("Earnings Date") or []]
        except Exception:  # noqa: BLE001 - informational only
            return "unknown"
        return upcoming(dates, pd.Timestamp.now(NY).tz_localize(None).normalize())


def upcoming(dates: list[pd.Timestamp], today: pd.Timestamp) -> str:
    """Yahoo's calendar keeps the last report until the next one is set: never call it 'next'."""
    future = sorted(d for d in dates if d >= today)
    if future:
        return future[0].strftime("%Y-%m-%d")
    last = max(dates).strftime("%Y-%m-%d") if dates else None
    return f"none scheduled (last report {last})" if last else "none listed"


# ---------------------------------------------------------------- option ladders


def ladder(market, ticker: str, direction: str, today: str, spot: float,
           rules: Rules) -> list[dict]:  # fmt: skip
    """Tradeable calls (long) or puts (short) at up to 3 expiries, ATM to ~15% OTM, with live
    quotes where IBKR has them, breakeven and the expiry's ATM implied move."""
    from horizon_trader.agents.market import nearest_expiry, requote

    t0 = pd.Timestamp(today)
    expiries = [e for e in market.expiries(ticker) if (pd.Timestamp(e) - t0).days >= 7]
    picked = []
    for d in rules.ladder_days:
        e = nearest_expiry(expiries, today, d)
        if e and e not in picked:
            picked.append(e)
    call = direction == "long"
    lo, hi = (0.97, 1.15) if call else (0.85, 1.03)
    rows = []
    for e in picked:
        calls, puts = market.chain(ticker, e)
        book = calls if call else puts
        atm_k = calls["strike"].iloc[(calls["strike"] - spot).abs().argmin()]
        window = book[(book["strike"] >= spot * lo) & (book["strike"] <= spot * hi)]
        if window.empty:
            continue
        step = max(1, len(window) // rules.ladder_strikes)
        pick = window.iloc[::step].head(rules.ladder_strikes)
        atm = pd.concat([calls[calls["strike"] == atm_k].head(1), puts[puts["strike"] == atm_k]
                         .head(1)])  # fmt: skip
        fresh = requote(market, pd.concat([pick, atm]))
        quoted, atm_q = fresh.iloc[: len(pick)], fresh.iloc[len(pick) :]
        implied = None
        if len(atm_q) == 2 and (atm_q["bid"] > 0).all():
            implied = float(((atm_q["bid"] + atm_q["ask"]) / 2).sum() / spot * 100)
        dte = (pd.Timestamp(e) - t0).days
        for _, r in quoted.iterrows():
            bid, ask = float(r["bid"]), float(r["ask"])
            mid = (bid + ask) / 2
            oi = 0 if pd.isna(r.get("openInterest")) else int(r.get("openInterest"))
            spread = (ask - bid) / mid if mid > 0 else float("inf")
            ok = (bid > 0 and ask >= rules.min_premium and spread <= rules.max_option_spread
                  and oi >= rules.min_open_interest)  # fmt: skip
            if not ok:
                continue
            k = float(r["strike"])
            be = k + ask if call else k - ask
            rows.append({
                "contract": str(r["contractSymbol"]), "ticker": ticker,
                "right": "C" if call else "P", "expiry": e, "dte": dte, "strike": k,
                "bid": bid, "ask": ask, "spread %": round(spread * 100, 1),
                "iv %": round(float(r.get("impliedVolatility", np.nan)) * 100, 1),
                "oi": oi, "cost/contract": round(ask * 100, 2),
                "breakeven": round(be, 2), "move to BE %": round((be / spot - 1) * 100, 1),
                "implied move to expiry %": None if implied is None else round(implied, 1),
                "quote": r.get("quote_source", "yahoo"),
            })  # fmt: skip
    return rows


# ---------------------------------------------------------------- positions and P&L


def held_qty(pos: dict) -> float:
    return pos.get("held", 0.0)


def expected_positions(state: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in state["positions"].values():
        if abs(held_qty(p)) > 1e-9:
            out[p["symbol"]] = out.get(p["symbol"], 0.0) + held_qty(p)
    return out


def reconcile(state: dict, actual: dict[str, float], tol: float = 1e-6) -> None:
    exp = expected_positions(state)
    gaps = {s: (exp.get(s, 0.0), actual.get(s, 0.0)) for s in sorted(exp.keys() | actual.keys())
            if abs(exp.get(s, 0.0) - actual.get(s, 0.0)) > tol}  # fmt: skip
    if gaps:
        lines = "\n".join(f"  {s}: ours {e:+g}, Alpaca {a:+g}" for s, (e, a) in gaps.items())
        raise GuardError(f"positions don't reconcile; fix before trading:\n{lines}")


def committed(state: dict, instrument: str) -> float:
    return sum(p["cost"] for p in state["positions"].values()
               if p["instrument"] == instrument and p["status"] in OPEN_STATES)  # fmt: skip


def mult(pos: dict) -> int:
    return 100 if pos["instrument"] == "option" else 1


def _book(pos: dict, o: dict, info: OrderInfo) -> list[dict]:
    rows = []
    for lf in info.legs:
        if lf.filled_qty <= 0 or lf.symbol != pos["symbol"]:
            continue
        signed = lf.filled_qty if lf.side == "buy" else -lf.filled_qty
        px = lf.avg_price if lf.avg_price is not None else info.avg_price
        pos["held"] = held_qty(pos) + signed
        pos["cash_flow"] = pos.get("cash_flow", 0.0) - signed * px * mult(pos)
        rows.append({
            "time": info.filled_at or "", "strategy": LEDGER, "source": "alpaca",
            "symbol": lf.symbol, "quantity": signed * mult(pos), "price": px,
            "ref_price": pos.get("limit") if o["role"] == "open" else math.nan,
            "open_price": math.nan, "commission": 0.0, "modeled_commission": 0.0,
            "exec_id": f"{info.client_id}:{lf.symbol}",
        })  # fmt: skip
    return rows


def sync(pos: dict, broker) -> list[dict]:
    """Book finished orders; move the position's status along."""
    rows = []
    for o in pos["orders"]:
        if o.get("booked"):
            continue
        info = broker.order(o["client_id"])
        if info is None:
            continue
        o |= {"status": info.status, "filled_qty": info.filled_qty, "avg_price": info.avg_price}
        if not info.final:
            continue
        rows += _book(pos, o, info)
        o["booked"] = True
        if o["role"] == "open":
            if info.filled_qty > 0:
                pos["status"] = "open"
                pos["qty"] = info.filled_qty
                if info.avg_price is not None:
                    pos["entry"] = info.avg_price
                    pos["cost"] = info.filled_qty * info.avg_price * mult(pos)
            else:
                pos |= {"status": "missed", "reason": f"entry {info.status}, no fill", "cost": 0.0}
        elif o["role"] == "stop" and info.filled_qty > 0:
            pos["close_reason"] = pos.get("close_reason") or "stop (broker)"
    if (
        pos["status"] in ("open", "closing")
        and abs(held_qty(pos)) < 1e-9
        and any(o["role"] in ("close", "stop") and o.get("filled_qty") for o in pos["orders"])
    ):
        pos["status"] = "closed"
        pos["realized"] = pos.get("cash_flow", 0.0)
    elif pos["status"] == "closing" and all(o.get("booked") for o in pos["orders"]
                                            if o["role"] == "close"):  # fmt: skip
        pos["status"] = "open"  # a close didn't fill: try again next run
    return rows


def working_stop(pos: dict) -> dict | None:
    return next((o for o in pos["orders"] if o["role"] == "stop" and not o.get("booked")), None)


# ---------------------------------------------------------------- order checks


def check_order(order: dict, ctx: dict, rules: Rules) -> tuple[dict | None, str]:
    """Resize or reject one decision-call order. `ctx`: today, equity, cash, state, ladders
    (contract -> row), quotes (ticker -> (bid, ask)), scan (ticker -> row), candidates
    (ticker -> direction), new (count so far). Returns (position, note) or (None, reason)."""
    t = order["ticker"].upper().strip()
    state, today, eq = ctx["state"], ctx["today"], ctx["equity"]
    live = [p for p in state["positions"].values() if p["status"] in OPEN_STATES]
    if t not in ctx["candidates"]:
        return None, f"{t} wasn't a step-1 candidate (no ladder or quote was built for it)"
    if any(p["ticker"] == t for p in live):
        return None, f"already holding {t} (one position per underlying)"
    if len(live) >= rules.max_positions:
        return None, f"{rules.max_positions} positions already open"
    if ctx["new"] >= rules.max_new:
        return None, f"already {rules.max_new} new positions this session"
    try:
        exit_by = pd.Timestamp(order["exit_by"]).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None, f"exit_by {order['exit_by']!r} isn't a date"
    last_day = prev_weekday(rules.close_all_from)
    if exit_by <= today:
        return None, f"exit_by {exit_by} isn't after today"
    exit_by = min(exit_by, last_day)
    stop, target = float(order["stop"]), float(order.get("target") or 0)
    spare_cash = ctx["cash"] - ctx.get("reserved", 0.0)
    notes = []

    if order["instrument"] == "shares":
        if ctx["candidates"][t] != "long":
            return None, "short shares aren't allowed: use puts"
        bid, ask = ctx["quotes"].get(t, (0.0, 0.0))
        if bid <= 0 or ask <= 0:
            return None, f"no stock quote for {t}"
        if (ask - bid) / ((ask + bid) / 2) > rules.max_stock_spread:
            return None, f"{t} quote too wide ({bid}/{ask})"
        s = ctx["scan"].get(t) or {}
        if ask < rules.min_price:
            return None, f"{t} under ${rules.min_price:.0f}"
        if s.get("$vol 20d M", 0) * 1e6 < rules.min_dollar_volume:
            return None, f"{t} trades under ${rules.min_dollar_volume / 1e6:.0f}M a day"
        if not 0 < stop < ask or (ask - stop) / ask > rules.max_stop_pct:
            return None, f"stop {stop} must be below {ask} and within {rules.max_stop_pct:.0%}"
        if target and target <= ask:
            return None, f"target {target} must be above {ask} (or 0)"
        limit = round(ask * (1 + rules.stock_pad), 2)
        room = rules.shares_total_pct * eq - committed(state, "shares")
        budget = min(rules.shares_idea_pct * eq, room, spare_cash)
        qty = min(math.floor(float(order["qty"])), math.floor(budget / limit))
        if qty < 1:
            return None, f"no room: shares budget ${max(budget, 0):,.0f} < one share at {limit}"
        if qty < math.floor(float(order["qty"])):
            notes.append(f"cut from {math.floor(float(order['qty']))} to {qty} shares")
        symbol, expiry, cost = t, None, qty * limit
    elif order["instrument"] == "option":
        row = ctx["ladders"].get(order["contract"])
        if row is None or row["ticker"] != t:
            return None, f"contract {order['contract']!r} isn't in {t}'s ladder"
        spot = ctx["spot"][t]
        call = row["right"] == "C"
        if call and not stop < spot or not call and not stop > spot:
            return None, f"stop {stop} on the wrong side of spot {spot:.2f} for a {row['right']}"
        if target and (call and target <= spot or not call and target >= spot):
            return None, f"target {target} on the wrong side of spot {spot:.2f}"
        exit_by = min(exit_by, prev_weekday(row["expiry"]))
        if exit_by <= today:
            return None, f"{order['contract']} expires too soon"
        limit = tick_up(row["ask"], multi_leg=False)
        room = rules.option_total_pct * eq - committed(state, "option")
        budget = min(rules.option_idea_pct * eq, room, spare_cash)
        want = math.floor(float(order["qty"]))
        qty = min(want, math.floor(budget / (limit * 100)))
        if qty < 1:
            return None, f"no room: premium budget ${max(budget, 0):,.0f} < one contract " \
                         f"(${limit * 100:,.0f})"  # fmt: skip
        if qty < want:
            notes.append(f"cut from {want} to {qty} contracts")
        symbol, expiry, cost = order["contract"], row["expiry"], qty * limit * 100
    else:
        return None, f"unknown instrument {order['instrument']!r}"

    if exit_by != order["exit_by"]:
        notes.append(f"exit_by moved to {exit_by}")
    pos = {
        "ticker": t, "instrument": order["instrument"], "symbol": symbol, "expiry": expiry,
        "direction": ctx["candidates"][t], "qty": float(qty), "limit": limit, "cost": cost,
        "stop": stop, "target": target, "exit_by": exit_by, "opened": today,
        "thesis": order["thesis"], "catalyst": order["catalyst"],
        "invalidation": order["invalidation"], "confidence": order["confidence"],
        "expected_move_pct": order["expected_move_pct"], "status": "opening", "held": 0.0,
        "cash_flow": 0.0, "orders": [], "close_reason": None, "closes": 0, "stops": 0,
    }  # fmt: skip
    return pos, "; ".join(notes) or "ok"


def mechanical_exit(pos: dict, today: str, spot: float | None, rules: Rules) -> str | None:
    """Exits code takes without asking the model."""
    if today >= rules.close_all_from:
        return "contest end"
    if pos["instrument"] == "option" and today >= prev_weekday(pos["expiry"]):
        return "day before expiry"
    if today >= pos["exit_by"]:
        return f"exit_by {pos['exit_by']}"
    if spot is None:
        return None
    long = pos["direction"] == "long"
    if pos["instrument"] == "option" and (spot <= pos["stop"] if long else spot >= pos["stop"]):
        return f"stop: {pos['ticker']} {spot:.2f} crossed {pos['stop']}"
    t = pos.get("target") or 0
    if t and (spot >= t if long else spot <= t):
        return f"target: {pos['ticker']} {spot:.2f} reached {t}"
    return None


# ---------------------------------------------------------------- briefing


def _table(df: pd.DataFrame, digits: int = 1) -> str:
    if df.empty:
        return "(none)"
    cols = list(df.columns)
    out = ["| | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for idx, row in df.iterrows():
        cells = []
        for v in row:
            if isinstance(v, float):
                cells.append("" if np.isnan(v) else f"{v:,.{digits}f}")
            else:
                cells.append(str(v))
        out.append(f"| {idx} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def trading_days_left(today: str, rules: Rules) -> int:
    from horizon_trader.ops.jobs import NYSE_HOLIDAYS

    days = pd.bdate_range(today, prev_weekday(rules.close_all_from))
    return int(sum(d.date() not in NYSE_HOLIDAYS for d in days))


def briefing(ctx: dict, rules: Rules) -> str:
    state, acct, today = ctx["state"], ctx["acct"], ctx["today"]
    start_eq = 5_000.0
    closed = [p for p in state["positions"].values() if p["status"] == "closed"]
    realized = sum(p.get("realized", 0.0) for p in closed)
    lines = [
        f"# Briefing, {today} {ctx['now']} ET",
        "",
        "## Account",
        f"Equity ${acct['equity']:,.2f} (started ${start_eq:,.0f}: "
        f"{(acct['equity'] / start_eq - 1) * 100:+.1f}%), cash ${acct['cash']:,.2f}, realized "
        f"P&L ${realized:+,.2f}. Trading since {state.get('start') or today}.",
        "",
        "## Open positions",
    ]
    live = [(pid, p) for pid, p in state["positions"].items() if p["status"] in OPEN_STATES]
    if not live:
        lines.append("(none)")
    for pid, p in live:
        mark = ctx["marks"].get(pid)
        pnl = "" if mark is None else (
            f", mark {mark:.2f}, P&L ${(mark * held_qty(p) * mult(p) - p['cost']):+,.0f} "
            f"({(mark * held_qty(p) * mult(p) / p['cost'] - 1) * 100:+.0f}%)" if p["cost"] else ""
        )  # fmt: skip
        spot = ctx["spot"].get(p["ticker"])
        lines.append(
            f"- **{pid}** {p['ticker']} {p['instrument']} {p['symbol']} x{held_qty(p):g} "
            f"({p['status']}), cost ${p['cost']:,.0f}{pnl}; {p['ticker']} now "
            f"{'?' if spot is None else f'{spot:.2f}'}, stop {p['stop']}, target "
            f"{p['target'] or 'none'}, exit_by {p['exit_by']}. Opened {p['opened']}. Thesis: "
            f"{p['thesis']} Catalyst: {p['catalyst']} Invalidation: {p['invalidation']}"
        )
    lines += ["", "## Track record (closed positions)"]
    if not closed:
        lines.append("(none yet)")
    for p in closed[-15:]:
        r = p.get("realized", 0.0)
        lines.append(f"- {p['ticker']} {p['instrument']} opened {p['opened']}: ${r:+,.0f} "
                     f"({r / p['cost'] * 100 if p['cost'] else 0:+.0f}%), "
                     f"{p.get('close_reason')}")  # fmt: skip
    if state.get("rejected"):
        lines += ["", "## Your orders code rejected or cut last session"]
        lines += [f"- {r}" for r in state["rejected"]]
    lines += ["", "## Your notebook (written by you last session)",
              state.get("notebook") or "(empty: first session)", "",
              "## Your recent session summaries"]  # fmt: skip
    lines += [f"- {s['stamp']}: {s['summary']}" for s in state.get("sessions", [])[-5:]] or [
        "(none)"
    ]
    if ctx.get("journal"):
        lines += ["", "## The house forecast journal's latest view (separate, conservative "
                  "agent; an input, not an instruction)", ctx["journal"]]  # fmt: skip
    lines += ["", ctx["packet"], "", "## Scan table (daily bars, last row = today's live price)",
              "RSI2 under 10 = short-term oversold; $vol = average daily dollar volume.", "",
              _table(ctx["scan_df"])]  # fmt: skip
    return "\n".join(lines) + "\n"


def journal_view() -> str:
    """The journal's last decision (bias, thesis, forecasts), read-only."""
    days = sorted((config.data_dir() / "journal" / "days").glob("*/decision.json"))
    if not days:
        return ""
    try:
        d = json.loads(days[-1].read_text(encoding="utf-8"))
        dec = d.get("decision", d)
        fc = "; ".join(f"{f.get('ticker')} {f.get('horizon_days')}d {f.get('direction')} "
                       f"(confidence {f.get('confidence')}/5)"
                       for f in dec.get("forecasts", []))  # fmt: skip
        return (f"{days[-1].parent.name}: regime {dec.get('regime')}, bias {dec.get('bias')}. "
                f"{dec.get('thesis', '')} Forecasts: {fc}")  # fmt: skip
    except (OSError, ValueError, AttributeError):
        return ""


def ladders_text(cands: list[dict], ladders: dict[str, list[dict]], quotes: dict,
                 earnings: dict) -> str:  # fmt: skip
    out = []
    for c in cands:
        t = c["ticker"]
        bid, ask = quotes.get(t, (0.0, 0.0))
        out += [
            f"## {t} ({c['direction']}, wants {c['instrument']})",
            f"Shares: bid {bid} / ask {ask} (IEX). Next earnings: {earnings.get(t, '?')}.",
        ]
        rows = ladders.get(t, [])
        if rows:
            df = pd.DataFrame(rows).set_index("contract").drop(columns=["ticker"])
            out.append(_table(df, 2))
        else:
            out.append("No tradeable options (none listed, or spreads/open interest fail).")
        out.append("")
    return "\n".join(out) or "(no candidates)"


# ---------------------------------------------------------------- order sending


def _send(broker, pos: dict, spec: OrderSpec, role: str, dry_run: bool) -> OrderInfo | None:
    if dry_run:
        log.info("DRY RUN %s %s: %s", role, pos.get("id"), spec)
        return None
    info = broker.order(spec.client_id) or broker.submit(spec)  # idempotent on a rerun
    pos["orders"].append({"client_id": spec.client_id, "role": role, "status": info.status,
                          "filled_qty": info.filled_qty, "avg_price": info.avg_price})  # fmt: skip
    return info


def place_stop(broker, pos: dict, dry_run: bool) -> None:
    """GTC stop at the broker for a filled shares position (whole shares)."""
    q = math.floor(held_qty(pos) + 1e-9)
    if pos["instrument"] != "shares" or q < 1 or working_stop(pos) or not pos.get("stop"):
        return
    pos["stops"] = pos.get("stops", 0) + 1
    spec = OrderSpec(f"{PREFIX}-{pos['id']}-s{pos['stops']}", (Leg(pos["symbol"], "sell"),),
                     float(q), None, tif="gtc", stop=round(pos["stop"], 2))  # fmt: skip
    _send(broker, pos, spec, "stop", dry_run)


def cancel_stop(broker, pos: dict, dry_run: bool) -> None:
    o = working_stop(pos)
    if o is None or dry_run:
        return
    broker.cancel(o["client_id"])
    for _ in range(10):
        info = broker.order(o["client_id"])
        if info is None or info.final:
            break
        time.sleep(0.5)
    sync(pos, broker)  # books a stop that filled before the cancel landed


def close_position(broker, pos: dict, why: str, dry_run: bool) -> None:
    cancel_stop(broker, pos, dry_run)
    q = held_qty(pos)
    if abs(q) < 1e-9:
        return
    pos |= {"status": "closing", "close_reason": why}
    pos["closes"] = pos.get("closes", 0) + 1
    side = "sell" if q > 0 else "buy"
    intent = f"{side}_to_close" if pos["instrument"] == "option" else ""
    spec = OrderSpec(f"{PREFIX}-{pos['id']}-c{pos['closes']}", (Leg(pos["symbol"], side, intent),),
                     abs(q), None)  # fmt: skip
    _send(broker, pos, spec, "close", dry_run)


def open_position(broker, pos: dict, dry_run: bool) -> OrderInfo | None:
    intent = "buy_to_open" if pos["instrument"] == "option" else ""
    spec = OrderSpec(f"{PREFIX}-{pos['id']}-open", (Leg(pos["symbol"], "buy", intent),),
                     pos["qty"], pos["limit"])  # fmt: skip
    return _send(broker, pos, spec, "open", dry_run)


# ---------------------------------------------------------------- the session


def default_runner(prompt: str, web: bool, schema: dict) -> dict:
    from horizon_trader.llm.codex import codex

    return codex(prompt, MODEL, web=web, schema=schema, effort=EFFORT, timeout=1800)


def _guards(broker, state: dict, today: str, rules: Rules, dry_run: bool) -> dict:
    if kill_switch_path().exists():
        raise GuardError(f"kill switch is on ({kill_switch_path()}); delete it to resume")
    acct = broker.account()
    if state["account"] is None:
        lo, hi = rules.first_equity
        if not lo <= acct["equity"] <= hi:
            raise GuardError(f"account {acct['account']} equity ${acct['equity']:,.0f} outside "
                             f"${lo:,.0f}-${hi:,.0f}: reset it to $5,000 first")  # fmt: skip
        if not dry_run:
            state["account"] = acct["account"]
    elif acct["account"] != state["account"]:
        raise GuardError(f"keys point at {acct['account']}, not {state['account']}: refusing")
    if not dry_run and state.get("start") is None:
        state["start"] = today
    return acct


def _sync_all(broker, state: dict, dry_run: bool, root) -> int:
    rows = []
    for pos in state["positions"].values():
        rows += sync(pos, broker)
    if not dry_run:
        _append_fills(rows, root)
    return len(rows)


def _spot(broker, ticker: str) -> float | None:
    try:
        bid, ask = broker.stock_quote(ticker)
    except Exception:  # noqa: BLE001 - a missing quote skips that check, nothing else
        return None
    return (bid + ask) / 2 if bid > 0 and ask > 0 else None


def _marks(broker, state: dict) -> dict[str, float]:
    out = {}
    opts = [p["symbol"] for p in state["positions"].values()
            if p["status"] in OPEN_STATES and p["instrument"] == "option"]  # fmt: skip
    q = {}
    if opts:
        try:
            q = broker.option_quotes(opts)
        except Exception:  # noqa: BLE001
            q = {}
    for pid, p in state["positions"].items():
        if p["status"] not in OPEN_STATES:
            continue
        if p["instrument"] == "option":
            bid, ask = q.get(p["symbol"], (0.0, 0.0))
            if bid > 0:
                out[pid] = (bid + ask) / 2
        elif (s := _spot(broker, p["symbol"])) is not None:
            out[pid] = s
    return out


def run(broker, market, bars_src, *, runner: Callable = default_runner, today: str | None = None,
        now: datetime | None = None, rules: Rules | None = None, root: Path | None = None,
        dry_run: bool = False, journal: str | None = None,
        force: bool = False) -> dict:  # fmt: skip
    rules = rules or Rules()
    now = now or datetime.now(NY)
    today = today or now.strftime("%Y-%m-%d")
    state = load_state(root)
    acct = _guards(broker, state, today, rules, dry_run)
    summary = {"date": today, "account": acct["account"], "closed": [], "opened": [],
               "rejected": [], "updated": [], "booked": 0}  # fmt: skip
    summary["booked"] = _sync_all(broker, state, dry_run, root)
    if not broker.is_open() and not force:
        log.info("market closed: syncing only")
        return _finish(broker, state, summary, today, root, dry_run)

    # stale entry orders from an earlier run today: cancel, then book what filled
    for pos in state["positions"].values():
        for o in pos["orders"]:
            if not o.get("booked") and o["role"] == "open" and not dry_run:
                broker.cancel(o["client_id"])
    summary["booked"] += _sync_all(broker, state, dry_run, root)
    reconcile(state, broker.positions())
    for pos in state["positions"].values():
        if pos["status"] == "open":
            place_stop(broker, pos, dry_run)

    spots = {p["ticker"]: _spot(broker, p["ticker"]) for p in state["positions"].values()
             if p["status"] in OPEN_STATES}  # fmt: skip
    for pid, pos in state["positions"].items():
        if pos["status"] != "open":
            continue
        why = mechanical_exit(pos, today, spots.get(pos["ticker"]), rules)
        if why:
            close_position(broker, pos, why, dry_run)
            summary["closed"].append(f"{pid} {pos['ticker']} ({why})")
    late = now.strftime("%H:%M") > rules.open_cutoff and not force
    if today >= rules.close_all_from or late:
        log.info("no LLM session: contest end or after %s", rules.open_cutoff)
        return _finish(broker, state, summary, today, root, dry_run)

    slog = SessionLog(root, f"{today}_{now.strftime('%H%M')}", dry_run)
    acct = broker.account()
    used = {"shares": committed(state, "shares"), "options": committed(state, "option")}
    universe = sorted(set(UNIVERSE) | {p["ticker"] for p in state["positions"].values()
                                       if p["status"] in OPEN_STATES})  # fmt: skip
    bars = bars_src.bars(universe)
    scan_df = scan_table(bars)
    from horizon_trader.agents.market import packet as market_packet

    try:
        packet_md, _ = market_packet(market, today)
    except Exception as exc:  # noqa: BLE001 - the scan table still gives the model a market
        packet_md = f"(market packet failed: {exc})"
    ctx = {"state": state, "acct": acct, "today": today, "now": now.strftime("%H:%M"),
           "marks": _marks(broker, state), "spot": {k: v for k, v in spots.items() if v},
           "packet": packet_md, "scan_df": scan_df,
           "journal": journal if journal is not None else journal_view()}  # fmt: skip
    brief = briefing(ctx, rules)
    pre = P.PREAMBLE.format(close_all_from=rules.close_all_from, last_open=rules.last_open,
                            today=today, days_left=trading_days_left(today, rules),
                            limits=rules.limits_text(acct["equity"], used))  # fmt: skip
    slog.text("briefing.md", brief)

    def call(name: str, prompt: str, web: bool, schema: dict) -> dict:
        slog.text(f"{name}.prompt.md", prompt)
        t0 = time.time()
        wrapper = runner(prompt, web, schema)
        wrapper["seconds"] = round(time.time() - t0, 1)
        slog.json(f"{name}.raw.json", wrapper)
        return wrapper["structured_output"]

    research = call("research", P.RESEARCH.format(preamble=pre, briefing=brief,
                                                  max_candidates=rules.max_candidates),
                    True, P.RESEARCH_SCHEMA)  # fmt: skip
    held_tickers = {p["ticker"] for p in state["positions"].values() if p["status"] in OPEN_STATES}
    cands = [c | {"ticker": c["ticker"].upper().strip()} for c in research["candidates"]]
    cands = [c for c in cands if c["ticker"] not in held_tickers][: rules.max_candidates]
    log.info("candidates: %s", ", ".join(f"{c['ticker']} {c['direction']}" for c in cands)
             or "none")  # fmt: skip

    quotes, ladders, earnings = {}, {}, {}
    extra = [c["ticker"] for c in cands if c["ticker"] not in bars]
    if extra:
        bars |= bars_src.bars(extra)
    scan = {t: scan_row(df) or {} for t, df in bars.items()}
    for c in cands:
        t = c["ticker"]
        try:
            quotes[t] = broker.stock_quote(t)
        except Exception:  # noqa: BLE001
            quotes[t] = (0.0, 0.0)
        bid, ask = quotes[t]
        spot = (bid + ask) / 2 if bid > 0 and ask > 0 else scan.get(t, {}).get("last")
        if spot:
            ctx["spot"][t] = float(spot)
        earnings[t] = bars_src.earnings_date(t)
        if c["instrument"] == "shares" or not spot:
            continue
        try:
            ladders[t] = ladder(market, t, c["direction"], today, float(spot), rules)
        except Exception as exc:  # noqa: BLE001 - that name just gets no options
            log.warning("ladder for %s failed: %s", t, exc)
    slog.json("ladders.json", {"quotes": quotes, "ladders": ladders, "earnings": earnings})

    decision_prompt = P.DECISION.format(
        preamble=pre,
        briefing=brief,
        max_new=rules.max_new,
        research=json.dumps(research, indent=1),
        ladders=ladders_text(cands, ladders, quotes, earnings),
    )
    decision = call("decision", decision_prompt, False, P.DECISION_SCHEMA)

    # position actions first: closes free budget for the new orders
    for a in decision["position_actions"]:
        pos = state["positions"].get(a["id"])
        if pos is None or pos["status"] != "open":
            continue
        if a["action"] == "close":
            close_position(broker, pos, f"model: {a['reason']}"[:200], dry_run)
            summary["closed"].append(f"{a['id']} {pos['ticker']} (model)")
        elif a["action"] == "update":
            new_stop = float(a["stop"])
            if pos["instrument"] == "shares" and new_stop != pos["stop"]:
                cancel_stop(broker, pos, dry_run)
            pos |= {"stop": new_stop, "target": float(a["target"] or 0),
                    "exit_by": min(a["exit_by"], prev_weekday(rules.close_all_from))}  # fmt: skip
            if pos["status"] == "open":
                place_stop(broker, pos, dry_run)
            summary["updated"].append(f"{a['id']} stop {pos['stop']} target {pos['target']} "
                                      f"exit_by {pos['exit_by']}")  # fmt: skip

    checks, rejected = [], []
    acct = broker.account()
    octx = {"today": today, "equity": acct["equity"], "cash": acct["cash"], "state": state,
            "ladders": {r["contract"]: r for rows in ladders.values() for r in rows},
            "quotes": quotes, "scan": scan, "spot": ctx["spot"], "new": 0, "reserved": 0.0,
            "candidates": {c["ticker"]: c["direction"] for c in cands}}  # fmt: skip
    for order in decision["orders"]:
        if today > rules.last_open:
            pos, note = None, f"no new positions after {rules.last_open}"
        else:
            pos, note = check_order(order, octx, rules)
        checks.append({"order": order, "accepted": pos is not None, "note": note})
        label = f"{order['ticker']} {order['instrument']} {order['contract']} x{order['qty']:g}"
        if pos is None:
            rejected.append(f"{label}: REJECTED, {note}")
            continue
        if note != "ok":
            rejected.append(f"{label}: accepted, {note}")
        state["seq"] = state.get("seq", 0) + 1
        pid = f"{today.replace('-', '')}-{state['seq']}"
        pos["id"] = pid
        try:
            info = open_position(broker, pos, dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad order doesn't stop the session
            rejected.append(f"{label}: broker refused, {exc}")
            continue
        octx["new"] += 1
        octx["reserved"] += pos["cost"]
        sent = f" -> {info.status}" if info else ""
        summary["opened"].append(
            f"{pid} {pos['ticker']} {pos['symbol']} x{pos['qty']:g} @ {pos['limit']}{sent}"
        )
        if not dry_run:
            state["positions"][pid] = pos
    slog.json("checks.json", checks)
    summary["rejected"] = rejected

    if not dry_run:  # give stock entries a moment, then put their stops at the broker
        for _ in range(15):
            pending = [p for p in state["positions"].values()
                       if p["status"] in ("opening", "closing")]  # fmt: skip
            if not pending:
                break
            time.sleep(2)
            _sync_all(broker, state, dry_run, root)
        for pos in state["positions"].values():
            if pos["status"] == "open":
                place_stop(broker, pos, dry_run)
        state["notebook"] = decision["notebook"]
        state["rejected"] = rejected
        state.setdefault("sessions", []).append(
            {"stamp": f"{today} {now.strftime('%H:%M')}", "summary": decision["session_summary"],
             "prompt_sha": P.prompt_sha(), "model": MODEL, "effort": EFFORT})  # fmt: skip
    summary["summary"] = decision["session_summary"]
    slog.json("summary.json", summary)
    return _finish(broker, state, summary, today, root, dry_run)


def _finish(broker, state, summary, today, root, dry_run) -> dict:
    if not dry_run:  # book closes sent this run (market orders usually fill at once)
        summary["booked"] += _sync_all(broker, state, dry_run, root)
    acct = broker.account()
    if not dry_run:
        write_ledger_files(acct, broker.positions(), state, today, root)
        save_state(state, root)
    summary["equity"] = acct["equity"]
    return summary


def sync_only(broker, *, today: str | None = None, root: Path | None = None) -> dict:
    """Evening: book fills, record equity, place stops (they queue for the next session)."""
    today = today or datetime.now(NY).strftime("%Y-%m-%d")
    state = load_state(root)
    acct = _guards(broker, state, today, Rules(), dry_run=False)
    summary = {"date": today, "account": acct["account"], "booked": 0}
    summary["booked"] = _sync_all(broker, state, False, root)
    for pos in state["positions"].values():
        if pos["status"] == "open":
            place_stop(broker, pos, False)
    return _finish(broker, state, summary, today, root, False)


def kill(broker) -> None:
    path = kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(NY).isoformat(), encoding="utf-8")
    broker.cancel_all()
    log.warning("kill switch ON (%s); open Alpaca orders cancelled", path)


def status(root: Path | None = None) -> None:
    state = load_state(root)
    print(f"account {state['account']}  trading since {state.get('start')}")
    for pid, p in state["positions"].items():
        print(f"  {pid:<12} {p['ticker']:<6} {p['instrument']:<7} {p['symbol']:<22} "
              f"{p['status']:<8} held {held_qty(p):g} cost ${p['cost']:,.0f} "
              f"stop {p['stop']} exit_by {p['exit_by']} {p.get('close_reason') or ''}")  # fmt: skip
    print("notebook:\n" + (state.get("notebook") or "(empty)"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["run", "sync", "status", "kill"])
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="research + decide + check, print the orders; send and save nothing",
    )
    p.add_argument("--no-ibkr", action="store_true", help="no live IBKR option quotes")
    p.add_argument(
        "--force",
        action="store_true",
        help="with --dry-run: run the model session even with the market closed",
    )
    a = p.parse_args()
    if a.force and not a.dry_run:
        raise SystemExit("--force only works with --dry-run")
    if a.command == "status":
        status()
        return
    if a.command in ("run", "sync") and not a.dry_run:
        config.require_ops(f"{a.command} the AI contest trader")
    from horizon_trader.agents.market import YahooMarket
    from horizon_trader.datasources.ibkr_quotes import IBKRQuotes
    from horizon_trader.execution.alpaca_broker import AlpacaPaper

    quotes = None if a.no_ibkr else IBKRQuotes(client_id=32)
    broker = AlpacaPaper("ALPACA_COMPETITION_AI", live_quotes=quotes)
    if a.command == "kill":
        kill(broker)
        return
    if a.command == "sync":
        s = sync_only(broker)
        print(f"{s['date']} account {s['account']} equity ${s['equity']:,.2f} "
              f"(fills booked: {s['booked']})")  # fmt: skip
        return
    s = run(broker, YahooMarket(quotes=quotes), YahooBars(), dry_run=a.dry_run, force=a.force)
    print(f"{s['date']} account {s['account']} equity ${s['equity']:,.2f} "
          f"(fills booked: {s['booked']})")  # fmt: skip
    for k in ("closed", "updated", "opened", "rejected"):
        for line in s.get(k, []):
            print(f"  {k}: {line}")
    if s.get("summary"):
        print(f"  decision: {s['summary']}")


if __name__ == "__main__":
    main()
