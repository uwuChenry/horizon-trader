"""AI competition account: execute the forecast journal's trade ideas on an Alpaca PAPER account.

    uv run python -m horizon_trader.agents.competition run [--dry-run]  # after the journal's run
    uv run python -m horizon_trader.agents.competition status
    uv run python -m horizon_trader.agents.competition kill             # KILL file + cancel orders

The journal (`agents/journal.py`) decides; this module only executes, so the journal's
pre-registered test is untouched (research/competition/README.md, "AI competition account").
Each run:
1. Guards: the kill switch, paper keys, the same Alpaca account as the first run, a ~$5k
   account on the first run.
2. Sync: book every finished order of ours (by client_order_id) into fills.csv.
3. Stop if any of our orders is still working, or if Alpaca's positions don't match ours.
4. Close (market orders, short legs first) what the journal closed, options one trading day
   before expiry (no exercise/assignment), and everything from `close_all_from`.
5. Open today's journal ideas (never the mirrors) at 2.5x the journal's sizing: limit orders
   at the current ask (debit spreads as one multi-leg order). An idea is only ever opened on
   its decision date; an unfilled day order is a missed trade, not retried.
6. Write equity.csv / fills.csv / state.json under data/live/competition_ai_paper/.

Quotes come from Alpaca's free 'indicative' options feed and IEX for stocks, and paper fills
are simulated, so fills.csv (Alpaca price vs the journal's modeled price) is an execution
check, not evidence about live costs.
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

import pandas as pd

from horizon_trader import config
from horizon_trader.execution.alpaca_broker import NY, Leg, OrderInfo, OrderSpec
from horizon_trader.execution.ledger import FILL_COLUMNS

log = logging.getLogger(__name__)

LEDGER = "competition_ai_paper"
PREFIX = "compai"  # client_order_id prefix
OPEN_STATES = {"opening", "open", "closing"}


class GuardError(RuntimeError):
    """A safety rail tripped: nothing (more) was submitted."""


@dataclass(frozen=True)
class Rules:
    # High-risk contest mode (owner, 2026-11-05): only first place counts, a wipeout is accepted.
    premium_cap: float = 1_000.0  # option debit per idea (journal: $150)
    premium_total: float = 4_000.0  # open option debit, 80% of the $5k account (journal: $600)
    shares_cap: float = 2_000.0  # per shares idea (journal: $2,500 of a $10k book)
    shares_total: float = 4_000.0  # open shares cost; cash caps options + shares together
    uncap_spreads: bool = True  # a debit-spread idea buys only its long leg: no capped upside
    low_conf: int = 2  # ideas with confidence <= this get...
    low_conf_scale: float = 0.5  # ...half the per-idea budget
    max_quote_spread: float = 0.30  # same as the journal: skip legs quoted wider than 30% of mid
    stock_pad: float = 0.002  # stock buy limit = ask * (1 + pad)
    max_stock_spread: float = 0.01  # IEX quotes can be thin: skip a stock quoted wider than 1%
    last_open: str = "2026-12-23"  # no new ideas after this date
    close_all_from: str = "2026-12-28"  # contest: everything closed by Dec 31
    open_cutoff: str = "15:57"  # ET; a later day order could be left unfilled at the bell
    first_equity: tuple[float, float] = (1_000.0, 10_000.0)  # first run: reset to ~$5k first
    fee_model: float = 0.65  # journal's per-contract fee assumption (for modeled_commission)


# ---------------------------------------------------------------- storage


def folder(root: Path | None = None) -> Path:
    return (root or config.data_dir() / "live") / LEDGER


def kill_switch_path() -> Path:
    return config.data_dir() / "live" / "KILL"  # the same switch the IBKR runs obey


def load_state(root: Path | None = None) -> dict:
    path = folder(root) / "follow.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"account": None, "start": None, "records": {}}


def save_state(state: dict, root: Path | None = None) -> None:
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "follow.json.tmp"
    tmp.write_text(json.dumps(state, indent=1, default=float), encoding="utf-8")
    tmp.replace(d / "follow.json")


def _append_fills(rows: list[dict], root: Path | None) -> None:
    if not rows:
        return
    path = folder(root) / "fills.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=FILL_COLUMNS).to_csv(
        path, mode="a", header=not path.exists(), index=False
    )


def _write_ledger_files(acct: dict, positions: dict, records: dict, today: str, root) -> None:
    d = folder(root)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "equity.csv"
    row = pd.DataFrame([{"date": today, "equity": acct["equity"], "cash": acct["cash"]}])
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str})
        row = pd.concat([old[old["date"] != today], row], ignore_index=True)
    row.to_csv(path, index=False)
    working = [
        {"symbol": r["underlying"], "quantity": r["qty"], "ref_price": r.get("limit"),
         "asof": r["date"]}
        for r in records.values() if r["status"] in ("opening", "closing")
    ]  # fmt: skip
    state = {"cash": acct["cash"], "holdings": positions, "pending": working}
    (d / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- pure helpers


def tick_up(price: float, multi_leg: bool) -> float:
    """Round a buy limit up to a valid increment ($0.01, or $0.05 for single legs >= $3)."""
    t = 0.01 if multi_leg or price < 3 else 0.05
    return round(math.ceil(price / t - 1e-9) * t, 2)


def prev_weekday(day: str) -> str:
    return (pd.Timestamp(day) - pd.offsets.BDay(1)).strftime("%Y-%m-%d")


def held(rec: dict) -> dict[str, float]:
    return {lg["symbol"]: lg["held"] for lg in rec["legs"] if abs(lg["held"]) > 1e-9}


def expected_positions(records: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for rec in records.values():
        for s, q in held(rec).items():
            out[s] = out.get(s, 0.0) + q
    return out


def reconcile(records: dict, actual: dict[str, float], tol: float = 1e-6) -> None:
    exp = expected_positions(records)
    gaps = {
        s: (exp.get(s, 0.0), actual.get(s, 0.0))
        for s in sorted(exp.keys() | actual.keys())
        if abs(exp.get(s, 0.0) - actual.get(s, 0.0)) > tol
    }
    if gaps:
        lines = "\n".join(f"  {s}: ours {e:+g}, Alpaca {a:+g}" for s, (e, a) in gaps.items())
        raise GuardError(f"positions don't reconcile; fix before trading:\n{lines}")


def committed(records: dict, asset: str) -> float:
    """Cost of open (or opening) positions of one asset class."""
    return sum(r["cost"] for r in records.values()
               if r["asset"] == asset and r["status"] in OPEN_STATES)  # fmt: skip


def close_reason(rec: dict, jpos: dict | None, today: str, rules: Rules) -> str | None:
    if today >= rules.close_all_from:
        return "contest end"
    if jpos is not None and jpos.get("status") == "closed":
        return f"journal ({jpos.get('exit_reason', 'closed')})"
    if rec["asset"] == "option" and today >= prev_weekday(rec["expiry"]):
        return "day before expiry"
    return None


def record_from_journal(p: dict, rules: Rules | None = None) -> dict:
    rules = rules or Rules()
    asset = "stock" if p["legs"][0]["type"] == "stock" else "option"
    structure, src = p["structure"], p["legs"]
    if rules.uncap_spreads and "spread" in structure:
        structure = structure.replace("_debit_spread", "") + " (spread uncapped)"
        src = [lg for lg in src if int(lg["side"]) > 0]
    legs = []
    for lg in src:
        side = int(lg["side"])
        ref = lg.get("ask") if side > 0 else lg.get("bid")
        legs.append(
            {
                "symbol": lg["symbol"],
                "side": side,
                "held": 0.0,
                "journal_price": float(ref) if ref is not None else p.get("unit_entry"),
            }
        )
    return {
        "id": p["id"], "date": p["date"], "underlying": p["underlying"],
        "structure": structure, "journal_structure": p["structure"], "asset": asset,
        "expiry": p.get("expiry"), "legs": legs, "confidence": p.get("confidence"),
        "journal_qty": p.get("qty"), "status": "skipped", "reason": "", "qty": 0.0,
        "limit": None, "cost": 0.0, "orders": [], "close_reason": None, "closes": 0,
    }  # fmt: skip


# ---------------------------------------------------------------- planning


def _scale(rec: dict, rules: Rules) -> float:
    conf = rec.get("confidence")
    return rules.low_conf_scale if conf is not None and conf <= rules.low_conf else 1.0


def plan_open(rec: dict, broker, rules: Rules, records: dict, acct: dict) -> OrderSpec | None:
    """Size and price one idea; on a skip, sets rec['reason'] and returns None."""
    if rec["asset"] == "stock":
        bid, ask = broker.stock_quote(rec["underlying"])
        if ask <= 0 or bid <= 0:
            rec["reason"] = "no stock quote"
            return None
        if (ask - bid) / ((ask + bid) / 2) > rules.max_stock_spread:
            rec["reason"] = f"IEX quote too wide ({bid}/{ask})"
            return None
        limit = round(ask * (1 + rules.stock_pad), 2)
        left = rules.shares_total - committed(records, "stock")
        budget = min(rules.shares_cap * _scale(rec, rules), left, acct["cash"])
        qty = math.floor(budget / limit * 1000) / 1000  # fractional shares
        if qty * limit < 1:
            rec["reason"] = f"stock budget used up (${budget:,.0f} left)"
            return None
        rec |= {"qty": qty, "limit": limit, "cost": qty * limit}
        return OrderSpec(f"{PREFIX}-{rec['id']}-open", (Leg(rec["underlying"], "buy"),), qty,
                         limit)  # fmt: skip

    multi = len(rec["legs"]) > 1
    need = 3 if multi else 2
    if acct.get("options_level", 0) < need:
        rec["reason"] = f"Alpaca options level {acct.get('options_level')} < {need}"
        return None
    quotes = broker.option_quotes([lg["symbol"] for lg in rec["legs"]])
    rec["quote_source"] = getattr(broker, "last_quote_source", "")
    for lg in rec["legs"]:
        bid, ask = quotes.get(lg["symbol"], (0.0, 0.0))
        if ask <= 0:
            rec["reason"] = f"no quote for {lg['symbol']}"
            return None
        mid = (bid + ask) / 2
        if (ask - bid) / mid > rules.max_quote_spread:
            rec["reason"] = f"quote too wide on {lg['symbol']} ({bid}/{ask})"
            return None
    debit = sum(quotes[lg["symbol"]][1] if lg["side"] > 0 else -quotes[lg["symbol"]][0]
                for lg in rec["legs"])  # fmt: skip
    if debit <= 0:
        rec["reason"] = "no debit at current quotes"
        return None
    limit = tick_up(debit, multi)
    left = rules.premium_total - committed(records, "option")
    budget = min(rules.premium_cap * _scale(rec, rules), left, acct["cash"])
    qty = math.floor(budget / (limit * 100))
    if qty < 1:
        rec["reason"] = f"one contract ${limit * 100:,.0f} > budget ${max(budget, 0):,.0f}"
        return None
    rec |= {"qty": float(qty), "limit": limit, "cost": qty * limit * 100}
    legs = tuple(
        Leg(lg["symbol"], "buy" if lg["side"] > 0 else "sell",
            "buy_to_open" if lg["side"] > 0 else "sell_to_open")
        for lg in rec["legs"]
    )  # fmt: skip
    return OrderSpec(f"{PREFIX}-{rec['id']}-open", legs, float(qty), limit)


def close_specs(rec: dict) -> list[list[OrderSpec]]:
    """Market orders closing what's held, in waves: short legs first, then long legs."""
    n = rec["closes"]
    waves = []
    for short in (True, False):
        wave = []
        for i, lg in enumerate(rec["legs"]):
            q = lg["held"]
            if abs(q) < 1e-9 or (q < 0) != short:
                continue
            side = "buy" if q < 0 else "sell"
            intent = "" if rec["asset"] == "stock" else f"{side}_to_close"
            wave.append(OrderSpec(f"{PREFIX}-{rec['id']}-c{n}-{i}",
                                  (Leg(lg["symbol"], side, intent),), abs(q), None))  # fmt: skip
        if wave:
            waves.append(wave)
    return waves


# ---------------------------------------------------------------- order sync


def _book(rec: dict, o: dict, info: OrderInfo, rules: Rules) -> list[dict]:
    """Apply a finished order's fills to the record's legs; return fills.csv rows."""
    rows = []
    mult = 100 if rec["asset"] == "option" else 1
    by_symbol = {lg["symbol"]: lg for lg in rec["legs"]}
    for lf in info.legs:
        if lf.filled_qty <= 0 or lf.symbol not in by_symbol:
            continue
        lg = by_symbol[lf.symbol]
        signed = lf.filled_qty if lf.side == "buy" else -lf.filled_qty
        lg["held"] += signed
        px = lf.avg_price if lf.avg_price is not None else info.avg_price
        ref = lg["journal_price"] if o["role"] == "open" else math.nan
        modeled = rules.fee_model * lf.filled_qty if mult == 100 else 0.0
        rows.append({
            "time": info.filled_at or "", "strategy": LEDGER, "source": "alpaca",
            "symbol": lf.symbol, "quantity": signed * mult, "price": px, "ref_price": ref,
            "open_price": math.nan, "commission": 0.0, "modeled_commission": modeled,
            "exec_id": f"{info.client_id}:{lf.symbol}",
        })  # fmt: skip
    return rows


def sync(rec: dict, broker, rules: Rules) -> list[dict]:
    rows = []
    for o in rec["orders"]:
        if o.get("booked"):
            continue
        info = broker.order(o["client_id"])
        if info is None:
            continue
        o |= {"status": info.status, "filled_qty": info.filled_qty, "avg_price": info.avg_price}
        if not info.final:
            continue
        rows += _book(rec, o, info, rules)
        o["booked"] = True
        if o["role"] == "open":
            if info.filled_qty > 0:
                rec["status"] = "open"
                rec["qty"] = info.filled_qty
                if info.avg_price is not None:
                    mult = 100 if rec["asset"] == "option" else 1
                    rec["cost"] = info.filled_qty * info.avg_price * mult
            else:
                rec |= {"status": "missed", "reason": f"entry order {info.status}, no fill",
                        "cost": 0.0}  # fmt: skip
    if rec["status"] == "closing" and not held(rec):
        rec["status"] = "closed"
    elif rec["status"] == "closing" and all(o.get("booked") for o in rec["orders"]):
        rec["status"] = "open"  # something didn't fill: try again on the next run
    return rows


def working(records: dict) -> list[str]:
    return [o["client_id"] for r in records.values() for o in r["orders"] if not o.get("booked")]


# ---------------------------------------------------------------- the run


def _send(broker, rec: dict, spec: OrderSpec, role: str, dry_run: bool) -> OrderInfo | None:
    if dry_run:
        log.info("DRY RUN %s %s: %s", role, rec["id"], spec)
        return None
    info = broker.order(spec.client_id) or broker.submit(spec)  # idempotent on a rerun
    rec["orders"].append({"client_id": spec.client_id, "role": role, "status": info.status,
                          "filled_qty": info.filled_qty, "avg_price": info.avg_price})  # fmt: skip
    return info


def run(
    broker,
    journal_positions: list[dict],
    *,
    today: str | None = None,
    now: datetime | None = None,
    rules: Rules | None = None,
    root: Path | None = None,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    rules = rules or Rules()
    now = now or datetime.now(NY)
    today = today or now.strftime("%Y-%m-%d")
    if kill_switch_path().exists():
        raise GuardError(f"kill switch is on ({kill_switch_path()}); delete it to resume")
    state = load_state(root)
    records: dict = state["records"]
    acct = broker.account()
    if state["account"] is None:
        lo, hi = rules.first_equity
        if not lo <= acct["equity"] <= hi:
            raise GuardError(
                f"account {acct['account']} equity ${acct['equity']:,.0f} is outside "
                f"${lo:,.0f}-${hi:,.0f}: reset this paper account to $5,000 before the first run"
            )
        if not dry_run:
            state |= {"account": acct["account"], "start": today}
    elif acct["account"] != state["account"]:
        raise GuardError(f"keys point at {acct['account']}, not {state['account']}: refusing")

    rows = []
    for rec in records.values():
        rows += sync(rec, broker, rules)
    if not dry_run:
        _append_fills(rows, root)
    summary = {"date": today, "account": acct["account"], "booked": len(rows), "closed": [],
               "opened": [], "skipped": [], "missed": []}  # fmt: skip

    still = working(records)
    can_trade = broker.is_open()
    if still:
        log.warning("orders still working (%s): sending nothing new", ", ".join(still))
        can_trade = False
    elif not can_trade:
        log.info("market closed: syncing only")
    if can_trade:
        reconcile(records, broker.positions())

    jmap = {p["id"]: p for p in journal_positions}
    if can_trade:
        for rec in records.values():
            if rec["status"] != "open":
                continue
            why = close_reason(rec, jmap.get(rec["id"]), today, rules)
            if why is None:
                continue
            rec |= {"status": "closing", "close_reason": why}
            for wave in close_specs(rec):
                try:
                    for spec in wave:
                        _send(broker, rec, spec, "close", dry_run)
                except Exception as exc:  # noqa: BLE001 - keep the run (and its state) going
                    log.error("close of %s failed: %s; retrying next run", rec["id"], exc)
                    if all(o.get("booked") for o in rec["orders"]):
                        rec["status"] = "open"
                    break
                if not dry_run:  # let the short legs fill before selling the long ones
                    for _ in range(20):
                        sleep(1)
                        if all((broker.order(s.client_id) or OrderInfo("", "", 0, None, None))
                               .final for s in wave):  # fmt: skip
                            break
            rec["closes"] += 1
            summary["closed"].append(f"{rec['id']} ({why})")

    start = state.get("start") or today
    ideas = [
        p
        for p in journal_positions
        if p.get("kind") == "idea" and p["id"] not in records and p["date"] >= start
    ]
    late = now.strftime("%H:%M") > rules.open_cutoff
    for p in ideas:
        rec = record_from_journal(p, rules)
        if p["date"] != today:
            rec |= {"status": "missed", "reason": "not executed on its decision date"}
        elif p.get("status") != "open":
            rec |= {"status": "missed", "reason": "journal already closed it"}
        elif today > rules.last_open:
            rec["reason"] = f"no new ideas after {rules.last_open}"
        elif not can_trade or late:
            if not can_trade and not still:
                rec |= {"status": "missed", "reason": "market closed when the follower ran"}
            elif late:
                rec |= {"status": "missed", "reason": f"follower ran after {rules.open_cutoff}"}
            else:
                continue  # orders still working: look again on the next run
        else:
            try:
                spec = plan_open(rec, broker, rules, records, acct)
                info = _send(broker, rec, spec, "open", dry_run) if spec is not None else None
            except Exception as exc:  # noqa: BLE001 - one bad idea doesn't stop the run
                spec = None
                rec |= {"reason": f"order failed: {exc}", "cost": 0.0}
            if spec is not None:
                rec["status"] = "opening"
                summary["opened"].append(
                    f"{rec['id']} {rec['structure']} {rec['underlying']} x{rec['qty']:g} "
                    f"@ {rec['limit']}" + (f" -> {info.status}" if info else "")
                )
        if rec["status"] == "skipped":
            summary["skipped"].append(f"{rec['id']}: {rec['reason']}")
        elif rec["status"] == "missed":
            summary["missed"].append(f"{rec['id']}: {rec['reason']}")
        if not dry_run:
            records[rec["id"]] = rec

    if not dry_run:
        acct = broker.account()
        _write_ledger_files(acct, broker.positions(), records, today, root)
        save_state(state, root)
    summary["equity"] = acct["equity"]
    return summary


def kill(broker) -> None:
    path = kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now(NY).isoformat(), encoding="utf-8")
    broker.cancel_all()
    log.warning("kill switch ON (%s); open Alpaca orders cancelled", path)


def status(root: Path | None = None) -> None:
    state = load_state(root)
    print(f"account {state['account']}  following since {state['start']}")
    for rec in state["records"].values():
        print(f"  {rec['id']:<14} {rec['structure']:<18} {rec['underlying']:<6} "
              f"{rec['status']:<8} qty {rec['qty']:g} cost ${rec['cost']:,.0f}  "
              f"{rec.get('close_reason') or rec.get('reason') or ''}")  # fmt: skip


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["run", "status", "kill"])
    p.add_argument("--dry-run", action="store_true", help="plan and print; send and save nothing")
    p.add_argument(
        "--keys", default="ALPACA_COMPETITION_AI",
        help="env prefix of the paper keys; any other prefix needs --dry-run",
    )  # fmt: skip
    p.add_argument(
        "--no-ibkr",
        action="store_true",
        help="Alpaca indicative option quotes only (default: live IBKR quotes first)",
    )
    a = p.parse_args()
    if a.command == "status":
        status()
        return
    if a.keys != "ALPACA_COMPETITION_AI" and not (a.command == "run" and a.dry_run):
        raise SystemExit("--keys other than ALPACA_COMPETITION_AI only works with run --dry-run")
    if a.command == "run" and not a.dry_run:
        from horizon_trader.config import require_ops

        require_ops("run the competition follower")
    from horizon_trader.agents import book, journal
    from horizon_trader.datasources.ibkr_quotes import IBKRQuotes
    from horizon_trader.execution.alpaca_broker import AlpacaPaper

    broker = AlpacaPaper(a.keys, live_quotes=None if a.no_ibkr else IBKRQuotes(client_id=32))
    if a.command == "kill":
        kill(broker)
        return
    s = run(broker, book.load(journal.root()), dry_run=a.dry_run)
    print(f"{s['date']} account {s['account']} equity ${s['equity']:,.2f} "
          f"(fills booked: {s['booked']})")  # fmt: skip
    for k in ("closed", "opened", "skipped", "missed"):
        for line in s[k]:
            print(f"  {k}: {line}")


if __name__ == "__main__":
    main()
