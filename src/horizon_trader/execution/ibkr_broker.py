"""Order-placing IBKR adapter: the `Broker` protocol on top of an ib_async connection.

PAPER ONLY. `paper_account` refuses any account whose id doesn't start with "DU", and there is
deliberately no switch to turn that off: live trading needs the owner's explicit go-ahead and a
code change.

How a daily run uses it (see run_daily --mode paper):
1. `sync_fills` books the strategy's new executions into its ledger, matched by `orderRef`.
2. `reconcile` checks that the ledgers' positions add up to what IBKR holds; any gap stops.
3. Targets -> `compute_orders` against the ledger (a virtual $5k, never NetLiquidation).
4. `submit_all` checks every order against the caps first, then sends market-on-open orders
   (tif OPG), which fill at the next open like the backtest. `transmit=False` asks IBKR for a
   what-if (commission and margin) instead and places nothing.

Kill switch: if <data_dir>/live/KILL exists, nothing is submitted. `kill()` creates it and
cancels every open order on the account.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from ib_async import IB, MarketOrder, OrderState, Stock

from horizon_trader.config import LiveSettings, data_dir
from horizon_trader.execution.broker import Order
from horizon_trader.execution.costs import CostModel
from horizon_trader.execution.ledger import Ledger

log = logging.getLogger(__name__)

PAPER_PREFIX = "DU"
REJECTED = {"Cancelled", "ApiCancelled", "Inactive"}
NY = ZoneInfo("America/New_York")


class GuardError(RuntimeError):
    """A safety rail tripped: nothing (more) was submitted."""


def kill_switch_path() -> Path:
    return data_dir() / "live" / "KILL"


def paper_account(ib: IB) -> str:
    """The single paper account behind this connection, or GuardError."""
    accounts = ib.managedAccounts()
    if len(accounts) != 1:
        raise GuardError(f"expected exactly one account, got {accounts}")
    if not accounts[0].startswith(PAPER_PREFIX):
        raise GuardError(f"{accounts[0]} is not a paper account (DU...): refusing to trade")
    return accounts[0]


@dataclass(frozen=True)
class WhatIf:
    order: Order
    commission: float
    margin_change: str
    warning: str


def _num(x: float) -> float:
    return float("nan") if x is None or abs(x) > 1e300 else float(x)  # IB's UNSET_DOUBLE


class IBKRBroker:
    def __init__(
        self,
        ib: IB,
        ledger: Ledger,
        limits: LiveSettings,
        *,
        transmit: bool,
        kill_switch: Path | None = None,
    ):
        self.ib = ib
        self.ledger = ledger
        self.limits = limits
        self.transmit = transmit
        self.kill_switch = kill_switch or kill_switch_path()
        self.account = paper_account(ib)
        self.submitted = 0
        self.what_ifs: list[WhatIf] = []

    # Broker protocol: sizing comes from the strategy's ledger, not the $1M paper account.
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

    def submit(self, order: Order, price: float):
        """Place one OPG order (returns the ib_async Trade), or ask for a what-if."""
        self.check([order], {order.symbol: price})
        contract = Stock(order.symbol, "SMART", "USD")
        ib_order = MarketOrder(
            "BUY" if order.quantity > 0 else "SELL",
            abs(order.quantity),
            tif="OPG",  # market-on-open: fills at the next open, like backtest/sim.py
            orderRef=self.ledger.name,
            account=self.account,
        )
        self.submitted += 1
        if self.transmit:
            return self.ib.placeOrder(contract, ib_order)
        self.ib.RequestTimeout = 15  # a rejected what-if never answers
        try:
            state: OrderState = self.ib.whatIfOrder(contract, ib_order)
        except TimeoutError:
            raise GuardError(
                f"no what-if answer for {order.symbol}: is 'Read-Only API' ticked in Gateway "
                "(Configure > Settings > API > Settings)?"
            ) from None
        if not isinstance(state, OrderState):  # ib_async returns [] after an IBKR error
            raise GuardError(f"IBKR rejected the what-if for {order.symbol} (error logged above)")
        self.what_ifs.append(
            WhatIf(order, _num(state.commission), state.initMarginChange, state.warningText)
        )
        return None

    def submit_all(self, orders: list[Order], prices: dict[str, float], asof: str) -> None:
        """All-or-nothing on the caps: every order is checked before the first is sent."""
        if self.transmit and (mine := self.open_orders()):
            raise GuardError(
                f"{len(mine)} open {self.ledger.name} orders already at IBKR (placed earlier "
                "today?); not placing more"
            )
        self.check(orders, prices)
        trades = [self.submit(o, prices[o.symbol]) for o in orders]
        if not self.transmit:
            return
        self.ib.sleep(2)  # let IBKR accept or reject
        rejected = [t for t in trades if t.orderStatus.status in REJECTED]
        accepted = [o for o, t in zip(orders, trades, strict=True) if t not in rejected]
        self.ledger.add_pending(accepted, prices, asof)
        if rejected:
            msgs = "; ".join(
                f"{t.contract.symbol}: {t.log[-1].message if t.log else t.orderStatus.status}"
                for t in rejected
            )
            raise GuardError(f"IBKR rejected {len(rejected)} of {len(trades)} orders: {msgs}")

    def open_orders(self) -> list:
        return [t for t in self.ib.openTrades() if t.order.orderRef == self.ledger.name]


def sync_fills(ib: IB, ledger: Ledger, costs: CostModel, opens: pd.DataFrame | None = None) -> int:
    """Book this strategy's new IBKR executions (by orderRef) into its ledger.

    Records IBKR's actual commission next to the cost model's, and the day's open when
    `opens` has it, so fills.csv measures slippage and fees directly. Pending orders that
    no longer have an open order at IBKR and never filled are dropped with a warning; the
    next run re-applies targets anyway. Returns the number of fills booked.
    """
    ib.reqExecutions()
    ib.sleep(1)  # commission reports arrive just after the executions
    seen = set(ledger.seen_exec_ids)
    new = sorted(
        (
            f
            for f in ib.fills()
            if f.execution.orderRef == ledger.name and f.execution.execId not in seen
        ),
        key=lambda f: f.execution.time,
    )
    for f in new:
        ex = f.execution
        qty = ex.shares if ex.side == "BOT" else -ex.shares
        symbol = f.contract.symbol
        modeled = costs.total(qty, ex.price)
        commission = f.commissionReport.commission if f.commissionReport.execId else math.nan
        if math.isnan(commission):
            log.warning("no commission report for %s %s yet; charging the model", symbol, ex.execId)
        when = pd.Timestamp(ex.time).tz_convert(NY)
        open_price = math.nan
        if opens is not None and symbol in opens:
            day = pd.Timestamp(when.date())
            if day in opens.index:
                open_price = float(opens.at[day, symbol])
        ledger.apply_fill(
            time=when.strftime("%Y-%m-%d %H:%M:%S"), source="ibkr", symbol=symbol,
            quantity=qty, price=ex.price,
            commission=modeled if math.isnan(commission) else commission,
            modeled_commission=modeled, ref_price=_take_pending(ledger, symbol, qty),
            open_price=open_price, exec_id=ex.execId,
        )  # fmt: skip

    still_open = {t.contract.symbol for t in ib.openTrades() if t.order.orderRef == ledger.name}
    for p in [p for p in ledger.pending if p.symbol not in still_open]:
        log.warning("%s order %+g from %s never filled; dropped", p.symbol, p.quantity, p.asof)
        ledger.pending.remove(p)
    return len(new)


def _take_pending(ledger: Ledger, symbol: str, qty: float) -> float:
    """Reduce the matching pending order by a (partial) fill; return the price it was sized on."""
    for p in ledger.pending:
        if p.symbol == symbol and (p.quantity > 0) == (qty > 0):
            p.quantity -= qty
            if abs(p.quantity) < 1e-9:
                ledger.pending.remove(p)
            return p.ref_price
    return math.nan


def reconcile(ib: IB, account: str, ledgers: list[Ledger], tol: float = 1e-4) -> None:
    """GuardError unless the ledgers' positions add up to IBKR's positions, share for share."""
    expected: dict[str, float] = {}
    for led in ledgers:
        for s, q in led.holdings.items():
            expected[s] = expected.get(s, 0.0) + q
    actual: dict[str, float] = {}
    for p in ib.positions(account):
        if p.position:
            actual[p.contract.symbol] = actual.get(p.contract.symbol, 0.0) + float(p.position)
    gaps = {
        s: (expected.get(s, 0.0), actual.get(s, 0.0))
        for s in sorted(expected.keys() | actual.keys())
        if abs(expected.get(s, 0.0) - actual.get(s, 0.0)) > tol
    }
    if gaps:
        lines = "\n".join(f"  {s}: ledger {e:+g}, IBKR {a:+g}" for s, (e, a) in gaps.items())
        raise GuardError(f"positions don't reconcile; fix before trading:\n{lines}")


def kill(ib: IB) -> None:
    """Turn the kill switch on and cancel every open order on the (paper) account."""
    paper_account(ib)
    path = kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(pd.Timestamp.now(tz=NY).isoformat(), encoding="utf-8")
    ib.reqGlobalCancel()
    log.warning("kill switch ON (%s); all open orders cancelled", path)
