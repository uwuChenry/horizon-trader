"""The daily book on an Alpaca PAPER account: `run_daily --mode alpaca`.

Same flow as the IBKR paper mode (`ibkr_broker.py`), on its own Alpaca paper account (keys
ALPACA_DAILY_BOOK_*):
1. `sync_fills` books each pending order's fill (matched by client_order_id
   `<ledger>-<signal date>-<symbol>`) at Alpaca's price, next to the day's open and the IBKR
   cost model's commission, so fills.csv measures slippage directly.
2. `reconcile` stops on any gap between the ledger and Alpaca's positions. The account is
   dedicated to the book, so every position must be ours.
3. Targets -> `compute_orders` against the ledger (a virtual `account.starting_cash`).
4. `submit_all` checks the caps, the kill switch and the pinned account for the whole batch,
   then sends fractional market DAY orders. Sent after the close, Alpaca queues them for the
   next open (verified on the paper API 2026-11-05), which matches the backtest's next-open
   fill. Fractional shares avoid the whole-share misweighting that kept the book shadow-only
   on IBKR.

Alpaca charges no commission (paper fills are simulated); the ledger records 0 and the IBKR
model's figure for comparison. Ledger: data/live/<strategy>_alpaca_paper/.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pandas as pd

from horizon_trader.config import LiveSettings, data_dir
from horizon_trader.execution.alpaca_broker import NY, Leg, OrderSpec
from horizon_trader.execution.broker import Order
from horizon_trader.execution.costs import CostModel
from horizon_trader.execution.ibkr_broker import GuardError  # run_daily catches this one
from horizon_trader.execution.ledger import Ledger

log = logging.getLogger(__name__)

PREFIX = "ALPACA_DAILY_BOOK"  # env prefix of the account's paper keys
SUFFIX = "_alpaca_paper"  # ledger name = <live.strategy><SUFFIX>
REJECTED = {"rejected", "canceled", "expired", "suspended", "stopped"}


def client_id(ledger: str, asof: str, symbol: str) -> str:
    return f"{ledger}-{asof}-{symbol}"


def kill_switch_path() -> Path:
    return data_dir() / "live" / "KILL"


class AlpacaBookBroker:
    def __init__(self, api, ledger: Ledger, limits: LiveSettings, kill_switch: Path | None = None):
        self.api, self.ledger, self.limits = api, ledger, limits
        self.kill_switch = kill_switch or kill_switch_path()
        self.account = api.account()["account"]
        pin = Ledger.directory(ledger.name, ledger.root) / "alpaca_account.json"
        if pin.exists():
            want = json.loads(pin.read_text(encoding="utf-8"))["account"]
            if want != self.account:
                raise GuardError(f"keys point at {self.account}, not {want}: refusing")
        else:
            pin.parent.mkdir(parents=True, exist_ok=True)
            pin.write_text(json.dumps({"account": self.account}), encoding="utf-8")
        self.submitted = 0

    # Broker protocol: sizing comes from the ledger
    def positions(self) -> dict[str, float]:
        return self.ledger.positions()

    def equity(self, prices: dict[str, float]) -> float:
        return self.ledger.equity(prices)

    def check(self, orders: list[Order], prices: dict[str, float]) -> None:
        if self.kill_switch.exists():
            raise GuardError(f"kill switch is on ({self.kill_switch}); delete it to resume")
        if self.submitted + len(orders) > self.limits.max_orders_per_day:
            raise GuardError(
                f"{self.submitted + len(orders)} orders > cap {self.limits.max_orders_per_day}"
            )
        for o in orders:
            value = abs(o.quantity) * prices[o.symbol]
            if value > self.limits.max_order_value:
                raise GuardError(
                    f"{o.symbol} order ${value:,.0f} > cap ${self.limits.max_order_value:,.0f}"
                )

    def submit_all(self, orders: list[Order], prices: dict[str, float], asof: str) -> None:
        """All-or-nothing on the caps; an order already at Alpaca (a rerun) isn't resent."""
        if waiting := [p for p in self.ledger.pending if p.asof != asof]:
            raise GuardError(
                f"{len(waiting)} orders from {waiting[0].asof} haven't finished at Alpaca "
                "(run before the open?); not planning on top of them"
            )
        self.check(orders, prices)
        accepted, rejected = [], []
        for o in orders:
            cid = client_id(self.ledger.name, asof, o.symbol)
            info = self.api.order(cid)
            if info is None:
                side = "buy" if o.quantity > 0 else "sell"
                spec = OrderSpec(cid, (Leg(o.symbol, side),), round(abs(o.quantity), 6), None)
                info = self.api.submit(spec)
                self.submitted += 1
            (rejected if info.status in REJECTED else accepted).append((o, info))
        self.ledger.add_pending([o for o, _ in accepted], prices, asof)
        if rejected:
            self.ledger.save()  # keep the accepted orders: their fills must be booked later
            msgs = "; ".join(f"{o.symbol}: {i.status}" for o, i in rejected)
            raise GuardError(f"Alpaca rejected {len(rejected)} of {len(orders)} orders: {msgs}")


def sync_fills(api, ledger: Ledger, costs: CostModel, opens: pd.DataFrame | None = None) -> int:
    """Book each pending order once it's done; partial fills are booked, the rest dropped
    (the next run re-applies targets). Returns the number of fills booked."""
    booked = 0
    seen = set(ledger.seen_exec_ids)
    for p in list(ledger.pending):
        cid = client_id(ledger.name, p.asof, p.symbol)
        info = api.order(cid)
        if info is None:
            log.warning("%s: no Alpaca order %s; dropped", p.symbol, cid)
            ledger.pending.remove(p)
            continue
        if not info.final:
            continue  # still waiting for the open
        if info.filled_qty > 0 and cid not in seen:
            qty = math.copysign(info.filled_qty, p.quantity)
            when = info.filled_at or pd.Timestamp.now(tz=NY).strftime("%Y-%m-%d %H:%M:%S")
            open_price = math.nan
            if opens is not None and p.symbol in opens:
                day = pd.Timestamp(when[:10])
                if day in opens.index:
                    open_price = float(opens.at[day, p.symbol])
            ledger.apply_fill(
                time=when, source="alpaca", symbol=p.symbol, quantity=qty,
                price=float(info.avg_price), commission=0.0,
                modeled_commission=costs.total(qty, float(info.avg_price)),
                ref_price=p.ref_price, open_price=open_price, exec_id=cid,
            )  # fmt: skip
            booked += 1
        elif info.filled_qty <= 0:
            log.warning("%s order %+g from %s ended %s unfilled", p.symbol, p.quantity, p.asof,
                        info.status)  # fmt: skip
        ledger.pending.remove(p)
    return booked


def reconcile(api, ledger: Ledger, tol: float = 1e-4) -> None:
    exp, act = ledger.holdings, api.positions()
    gaps = {
        s: (exp.get(s, 0.0), act.get(s, 0.0))
        for s in sorted(exp.keys() | act.keys())
        if abs(exp.get(s, 0.0) - act.get(s, 0.0)) > tol
    }
    if gaps:
        lines = "\n".join(f"  {s}: ledger {e:+g}, Alpaca {a:+g}" for s, (e, a) in gaps.items())
        raise GuardError(f"positions don't reconcile; fix before trading:\n{lines}")
