"""Execute the existing IBKR ORB signal on its own Alpaca PAPER account (ALPACA_ORB_*).

    uv run python -m horizon_trader.intraday.orb_alpaca run     # start before 09:30 ET
    uv run python -m horizon_trader.intraday.orb_alpaca status

Selection, sizing and history come from orb_live; IBKR is used read-only for the signal.
The virtual $5k ledger is data/live/orb_alpaca_paper/, never Alpaca's account equity.
Alpaca cannot short hard-to-borrow names. There is no GTD: this runner cancels the entry
itself at 15:44. The stop is a separate order sent just after entry fills are observed,
leaving a roughly 2-second unprotected window. Keep the runner awake through the close.
On half days the entry cutoff moves to 16 minutes before the session close. The stop stays
on until 5 minutes before the close; then a day market order closes the position, resent
(up to 3 times) if it is rejected or expires. Market-on-close was dropped: Alpaca paper let
an accepted MOC expire unfilled on 2026-11-10 and the position stayed overnight.
A ledger that starts the day holding anything (a failed exit) is closed first: market on
open before 09:28, else a day market order; the day stops if that doesn't fill.
Paper fills are simulated: this measures mechanics, not real slippage. Actual commission
is $0; the configured IBKR model (Tiered by default) is recorded alongside for comparison.
Client ids, saved order intents and final fills allow a restart without sending twice.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from dataclasses import asdict, replace

import pandas as pd

from horizon_trader.config import LiveSettings, load_settings
from horizon_trader.execution import alpaca_book
from horizon_trader.execution.alpaca_broker import AlpacaPaper, Leg, OrderSpec
from horizon_trader.execution.broker import Order
from horizon_trader.execution.costs import ibkr_costs
from horizon_trader.execution.ibkr_broker import GuardError
from horizon_trader.execution.ledger import Ledger
from horizon_trader.intraday import orb_live
from horizon_trader.intraday.noise_live import Clock, append_event
from horizon_trader.intraday.orb_live import ACCOUNT, ENTRY_CUTOFF, Plan

log = logging.getLogger("horizon_trader.orb_alpaca")

PREFIX = "ALPACA_ORB"
LEDGER = "orb_alpaca_paper"
STARTING_CASH = 5_000.0
IB_CLIENT_ID = 22
LIMITS = LiveSettings(strategy="orb_alpaca", max_order_value=25_000.0, max_orders_per_day=10)
POLL = 2
MOC_BY = "15:45:00"  # reference for the half-day cutoff spacing only
EXIT_BEFORE_CLOSE = pd.Timedelta(minutes=5)
MAX_EXITS = 3
OPG_LEAD = pd.Timedelta(minutes=2)  # Alpaca takes market-on-open orders until 09:28
NY = "America/New_York"


IBKR_PLAN_DEADLINE = "09:38:00"  # after this, scan ourselves (the IBKR runner didn't decide)


def resize(ibkr_plan: dict, equity: float) -> Plan | None:
    """The IBKR runner's pick, sized for this ledger's equity with orb_live's own rule."""
    c = pd.Series(
        {"side": ibkr_plan["side"], "or_high": ibkr_plan["level"], "or_low": ibkr_plan["level"],
         "atr": ibkr_plan["atr"], "relvol": ibkr_plan["relvol"]},
        name=ibkr_plan["ticker"],
    )  # fmt: skip
    return orb_live.plan_trade(c, equity)


def ibkr_day_log(today, root=None) -> dict | None:
    path = Ledger.directory(orb_live.STRATEGY, root) / "days" / f"{today}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # missing, or caught mid-write
        return None


def plan_day(today, equity: float, day_log: dict, clock=None, root=None) -> Plan | None:
    """Follow the IBKR runner's 09:35 decision (data/live/orb/days/<day>.json), so both
    brokers trade the same pick and IBKR never sees two identical history requests within
    seconds (a pacing violation). Scan ourselves only if it hasn't decided by 09:38."""
    clock = clock or Clock()
    deadline = pd.Timestamp(f"{today} {IBKR_PLAN_DEADLINE}", tz=NY)
    while True:
        got = ibkr_day_log(today, root)
        if got and got.get("plan"):
            day_log["source"] = "ibkr runner"
            plan = resize(got["plan"], equity)
            if plan is None:
                day_log["decision"] = "size below 1 share"
            return plan
        if got and got.get("decision"):
            day_log["source"] = "ibkr runner"
            day_log["decision"] = f"IBKR runner: {got['decision']}"
            return None
        if clock.now() >= deadline:
            break
        clock.sleep(5)
    log.warning("no IBKR ORB decision by %s; scanning ourselves", IBKR_PLAN_DEADLINE)
    day_log["source"] = "own scan"
    from horizon_trader.execution.ibkr import connect

    feats = orb_live.history(today)
    ib = connect(readonly=True, client_id=IB_CLIENT_ID)
    try:
        plan, _ = orb_live.scan_and_plan(ib, today, feats, equity, day_log)
        return plan
    finally:
        ib.disconnect()


class Runner:
    def __init__(self, api, clock, ledger, broker, today, close_ts, day_log, path):
        self.api, self.clock, self.ledger, self.broker = api, clock, ledger, broker
        self.today, self.close_ts, self.day_log, self.path = today, close_ts, day_log, path
        self.events = path.parent.parent / "events.jsonl"
        self.plan = Plan(**day_log["plan"]) if day_log.get("plan") else None
        self.costs = ibkr_costs(load_settings().costs.plan, 0.0)
        self.orders = {}
        # Preserve the normal session's 15:44 -> 15:45 -> 16:00 spacing on half days.
        cutoff = pd.Timestamp(f"{today} {ENTRY_CUTOFF}", tz=NY)
        moc_by = pd.Timestamp(f"{today} {MOC_BY}", tz=NY)
        self.cutoff = min(cutoff, close_ts - pd.Timedelta(minutes=15) - (moc_by - cutoff))

    def cid(self, tag):
        return f"orba-{self.today}-{tag}"

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.day_log, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)

    def write(self, kind, **fields):
        append_event(self.events, self.clock, kind, **fields)

    def decision(self, reason):
        self.day_log["decision"] = reason
        self.write("decision", reason=reason)
        self.save()

    def recover(self):
        ids = list(dict.fromkeys([self.cid("entry"), *self.day_log.get("client_ids", [])]))
        # Also find an order accepted immediately before a crash, without a saved response.
        for tag in ("stop", "exit"):
            n = 1
            while (info := self.api.order(self.cid(f"{tag}{n}"))) is not None:
                self.orders[info.client_id] = info
                if info.client_id not in ids:
                    ids.append(info.client_id)
                n += 1
        for cid in ids:
            if (info := self.api.order(cid)) is not None:
                self.orders[cid] = info
        self.refresh()

    def refresh(self):
        # Final orders are immutable; polling only working orders stays well below the
        # paper API's request limit even after several stop replacements.
        for cid, info in list(self.orders.items()):
            if not info.final and (current := self.api.order(cid)) is not None:
                self.orders[cid] = current
        statuses = {cid: asdict(info) for cid, info in self.orders.items()}
        changed = statuses != self.day_log.get("statuses", {})
        if changed:
            self.day_log["statuses"] = statuses
            self.day_log["client_ids"] = list(
                dict.fromkeys([*self.day_log.get("client_ids", []), *self.orders])
            )
            self.save()
        self.broker.submitted = len(self.orders)
        for cid, info in self.orders.items():
            if info.final:
                self.book(cid, info)

    def book(self, cid, info):
        """Only final cumulative fills are booked, once per client id."""
        if info.filled_qty <= 0 or cid in self.ledger.seen_exec_ids:
            return
        if self.plan is None:
            raise GuardError("orders exist without a saved ORB plan")
        entry = cid == self.cid("entry")
        stop = cid.startswith(self.cid("stop"))
        qty = info.filled_qty * self.plan.side * (1 if entry else -1)
        ref = self.plan.level if entry else self.plan.stop_px if stop else math.nan
        self.ledger.apply_fill(
            time=info.filled_at or self.clock.now().strftime("%Y-%m-%d %H:%M:%S"),
            source="alpaca", symbol=self.plan.ticker, quantity=qty, price=float(info.avg_price),
            commission=0.0, modeled_commission=self.costs.total(qty, float(info.avg_price)),
            ref_price=ref, exec_id=cid,
        )  # fmt: skip
        self.ledger.save()
        self.write("fill", cid=cid, qty=qty, price=info.avg_price)
        if entry:
            log.info("entry filled %g @ %g", info.filled_qty, info.avg_price)
        elif stop:
            log.info("stopped out %g @ %g", info.filled_qty, info.avg_price)

    def reconcile(self):
        # A restarted, working order may already have partial fills. Compare those to the
        # account too, but keep the persistent ledger final-only (one execution id per order).
        holdings = self.ledger.positions()
        for cid, info in self.orders.items():
            if not info.final and info.filled_qty and cid not in self.ledger.seen_exec_ids:
                if self.plan is None:
                    raise GuardError("partial fills without a saved ORB plan")
                sign = self.plan.side * (1 if cid == self.cid("entry") else -1)
                symbol = self.plan.ticker
                holdings[symbol] = holdings.get(symbol, 0.0) + sign * info.filled_qty
        alpaca_book.reconcile(self.api, replace(self.ledger, holdings=holdings))

    def send(self, tag, qty, *, stop=None, limit=None, tif="day"):
        cid = self.cid(tag)
        if (info := self.api.order(cid)) is not None:
            self.orders[cid] = info
            return info
        sign = self.plan.side * (1 if tag == "entry" else -1)
        spec = OrderSpec(cid, (Leg(self.plan.ticker, "buy" if sign > 0 else "sell"),),
                         qty, limit, tif, stop)  # fmt: skip
        # Save intent before submission: an interrupted request can have been accepted.
        ids = self.day_log.setdefault("client_ids", [])
        if cid not in ids:
            ids.append(cid)
        self.day_log.setdefault("orders", {})[cid] = asdict(spec)
        self.save()
        info = self.api.submit(spec)
        self.orders[cid] = info
        self.broker.submitted += 1
        self.write("order", cid=cid, spec=asdict(spec), status=info.status)
        self.refresh()
        if info.status == "rejected":
            raise GuardError(f"Alpaca rejected {cid}")
        return info

    def cancel(self, cid):
        info = self.api.order(cid)
        if info is None or info.final:
            return
        self.api.cancel(cid)
        self.write("order", cid=cid, action="cancel")
        until = self.clock.now() + pd.Timedelta(seconds=60)
        while True:
            self.refresh()
            if self.orders[cid].final:
                return
            if self.clock.now() >= until:
                raise GuardError(f"{cid} cancellation not final after 60s; refusing another exit")
            self.clock.sleep(POLL)

    def stops(self):
        return {cid: info for cid, info in self.orders.items() if cid.startswith(self.cid("stop"))}

    def exits(self):
        return {cid: info for cid, info in self.orders.items() if cid.startswith(self.cid("exit"))}

    def remaining(self):
        entry = self.orders.get(self.cid("entry"))
        exited = sum(
            info.filled_qty for cid, info in self.orders.items() if cid != self.cid("entry")
        )
        qty = (entry.filled_qty if entry else 0) - exited
        if qty < -1e-9:
            raise GuardError("ORB exits exceed entry fills")
        return max(0.0, qty)

    def protect(self):
        active = [(cid, info) for cid, info in self.stops().items() if not info.final]
        if len(active) > 1:
            raise GuardError("multiple working ORB stops")
        qty = self.remaining()
        if active:
            cid, info = active[0]
            spec = self.day_log.get("orders", {}).get(cid)
            if spec and abs(spec["qty"] - info.filled_qty - qty) < 1e-9:
                return
            self.cancel(cid)
            self.refresh()  # the old stop or entry may fill while cancellation is pending
            qty = self.remaining()
        if qty:
            n = max((int(cid.rsplit("stop", 1)[1]) for cid in self.stops()), default=0) + 1
            self.send(f"stop{n}", qty, stop=self.plan.stop_px)

    def monitor(self):
        exit_at = self.close_ts - EXIT_BEFORE_CLOSE
        # Once the close has been sent, a restart must leave the entry and stops alone.
        if not self.exits():
            while self.clock.now() < self.cutoff:
                self.refresh()
                entry = self.orders[self.cid("entry")]
                if self.broker.kill_switch.exists() or any(
                    info.status == "filled" for info in self.stops().values()
                ):
                    self.cancel(entry.client_id)
                    self.refresh()
                    entry = self.orders[entry.client_id]
                if entry.final and not self.remaining():
                    break
                self.protect()
                self.clock.sleep(
                    max(0, min(POLL, (self.cutoff - self.clock.now()).total_seconds()))
                )

            self.cancel(self.cid("entry"))
            self.refresh()
            if not self.remaining() and not self.orders[self.cid("entry")].filled_qty:
                log.info("no fill by 15:44; entry cancelled")
                self.decision("no fill by 15:44; entry cancelled")
            # Hold with the stop working until shortly before the close.
            while self.remaining() and self.clock.now() < exit_at:
                self.protect()
                self.clock.sleep(max(0, min(POLL, (exit_at - self.clock.now()).total_seconds())))
                self.refresh()
            for cid in self.stops():
                self.cancel(cid)
            self.refresh()
        self.close_out()

        # Poll through the close, then allow up to ten more minutes for final settlement.
        after_close = self.close_ts + pd.Timedelta(minutes=2)
        while self.clock.now() < after_close:
            self.clock.sleep(min(60, (after_close - self.clock.now()).total_seconds()))
        until = max(after_close, self.clock.now()) + pd.Timedelta(minutes=10)
        while True:
            self.refresh()
            if all(info.final for info in self.orders.values()) or self.clock.now() >= until:
                break
            self.clock.sleep(POLL)
        self.ledger.save()
        self.reconcile()
        if self.ledger.holdings or self.remaining():
            log.error("not flat after the close")
            self.decision("not flat after the close")
            orb_live.alert(
                f"ORB (Alpaca paper) not flat: {self.ledger.holdings}",
                "The next run closes it at the open.",
            )
        else:
            self.equity()

    def close_out(self):
        """Day market orders until flat: resend if one ends (rejected/expired/canceled) with
        shares left, at most MAX_EXITS, and only while the session is open."""
        while True:
            self.refresh()
            qty = self.remaining()
            working = [info for info in self.exits().values() if not info.final]
            if not qty and not working:
                return
            if working:
                if self.clock.now() >= self.close_ts + pd.Timedelta(minutes=2):
                    return
                self.clock.sleep(POLL)
                continue
            n = len(self.exits()) + 1
            if n > MAX_EXITS or self.clock.now() >= self.close_ts:
                return
            try:
                self.send(f"exit{n}", qty, tif="day")
            except GuardError as exc:  # rejected: count it and try again
                log.error("%s", exc)
                self.clock.sleep(POLL)
                continue
            log.info("sent market exit %d for %g", n, qty)

    def close_leftovers(self, open_ts):
        """Positions a failed exit left overnight: market on open before 09:28, else a day
        market order; one day-market retry for anything left. Books each final fill."""
        for symbol in list(self.ledger.holdings):
            for tag in ("left", "left2"):
                rest = self.ledger.holdings.get(symbol, 0.0)
                if not rest:
                    break
                cid = self.cid(f"{tag}-{symbol}")
                info = self.api.order(cid)
                if info is None:
                    opg = tag == "left" and self.clock.now() < open_ts - OPG_LEAD
                    side = "sell" if rest > 0 else "buy"
                    spec = OrderSpec(cid, (Leg(symbol, side),), abs(rest), None,
                                     "opg" if opg else "day")  # fmt: skip
                    info = self.api.submit(spec)
                    self.write("order", cid=cid, spec=asdict(spec), status=info.status)
                    log.info("leftover %s %g: sent %s %g (%s)", symbol, rest, side, abs(rest),
                             spec.tif)  # fmt: skip
                deadline = max(open_ts, self.clock.now()) + pd.Timedelta(minutes=5)
                while not info.final and self.clock.now() < deadline:
                    self.clock.sleep(POLL)
                    info = self.api.order(cid)
                if info.filled_qty and cid not in self.ledger.seen_exec_ids:
                    qty = -math.copysign(info.filled_qty, rest)
                    self.ledger.apply_fill(
                        time=info.filled_at or self.clock.now().strftime("%Y-%m-%d %H:%M:%S"),
                        source="alpaca", symbol=symbol, quantity=qty,
                        price=float(info.avg_price), commission=0.0,
                        modeled_commission=self.costs.total(qty, float(info.avg_price)),
                        exec_id=cid,
                    )  # fmt: skip
                    self.ledger.save()
                    self.write("fill", cid=cid, qty=qty, price=info.avg_price)
                    log.info("leftover %s closed %g @ %g", symbol, qty, info.avg_price)
                if not info.final:
                    self.api.cancel(cid)
        if self.ledger.holdings:
            orb_live.alert(f"ORB (Alpaca paper) leftover not closed: {self.ledger.holdings}")
            raise GuardError(f"leftover positions not closed: {self.ledger.holdings}")

    def equity(self):
        self.ledger.save()
        equity = self.ledger.record_equity(str(self.today), {})
        log.info(f"{LEDGER}: equity ${equity:,.2f}")


def run(api=None, clock=None, root=None, plan_fn=None) -> None:
    clock = clock or Clock()
    today = clock.now().date()
    api = api if api is not None else AlpacaPaper(PREFIX)
    folder = Ledger.directory(LEDGER, root)
    session = api.session(str(today))
    if session is None:
        log.warning("market closed today")
        append_event(folder / "events.jsonl", clock, "skip", reason="market closed today")
        return
    close_ts = pd.Timestamp(f"{today} {session[1]}", tz=NY)
    ledger = Ledger.load(LEDGER, STARTING_CASH, root)
    broker = alpaca_book.AlpacaBookBroker(api, ledger, LIMITS)
    path = folder / "days" / f"{today}.json"
    day_log = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    runner = Runner(api, clock, ledger, broker, today, close_ts, day_log, path)
    runner.write("start", account=broker.account, cash=ledger.cash)
    runner.recover()
    runner.reconcile()
    if not runner.orders and ledger.holdings:
        runner.close_leftovers(pd.Timestamp(f"{today} {session[0]}", tz=NY))
        runner.reconcile()
    if runner.orders and runner.cid("entry") not in runner.orders:
        raise GuardError("ORB orders exist without today's entry")
    if runner.cid("entry") in runner.orders:
        if runner.plan is None:
            raise GuardError("entry exists without a saved ORB plan")
    else:
        if clock.now() >= runner.cutoff:
            runner.decision("entry cutoff passed")
            runner.equity()
            return
        if plan_fn is not None:
            runner.plan = plan_fn(today, ledger.cash, day_log)
        else:
            runner.plan = plan_day(today, ledger.cash, day_log, clock, root)
        if runner.plan is None:
            runner.decision(day_log.get("decision", "no plan"))
            runner.equity()
            return
        plan = runner.plan
        day_log["plan"] = asdict(plan)
        runner.save()
        runner.write("plan", plan=asdict(plan))
        log.info(
            "plan: %s %s %g @ %g stop %g",
            plan.ticker,
            "long" if plan.side > 0 else "short",
            plan.qty,
            plan.level,
            plan.stop_px,
        )
        broker.check([], {})
        if plan.qty * plan.level > ACCOUNT.leverage * ledger.cash * 1.01:
            raise GuardError("ORB entry exceeds leverage cap")
        asset = api.asset(plan.ticker)
        if not asset["tradable"]:
            runner.decision("not tradable at Alpaca")
            runner.equity()
            return
        if plan.side < 0 and not (asset["shortable"] and asset["easy_to_borrow"]):
            runner.decision("not shortable at Alpaca")
            runner.equity()
            return
        broker.check([Order(plan.ticker, plan.side * plan.qty)], {plan.ticker: plan.level})
        # Planning can wait for the scanner; recheck the deadline immediately before entry.
        if clock.now() >= runner.cutoff:
            runner.decision("entry cutoff passed")
            runner.equity()
            return
        runner.decision("entry submitted")
        runner.send("entry", plan.qty, stop=plan.level, limit=plan.level)
    runner.monitor()


def status(root=None) -> None:
    ledger = Ledger.load(LEDGER, STARTING_CASH, root)
    print(f"{LEDGER}: cash ${ledger.cash:,.2f}, positions {ledger.holdings or 'flat'}")
    path = Ledger.directory(LEDGER, root) / "equity.csv"
    if path.exists():
        print(pd.read_csv(path).tail(5).to_string(index=False))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("action", choices=("run", "status"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.action == "status":
        status()
    else:
        from horizon_trader.config import require_ops

        require_ops("orb_alpaca run")
        try:
            run()
        except GuardError as e:
            raise SystemExit(f"STOPPED: {e}") from None


if __name__ == "__main__":
    main()
