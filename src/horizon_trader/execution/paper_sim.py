"""In-memory broker for dry runs, tests, and the backtester. Fills immediately at the given
reference price, adjusted by the cost model's slippage and commission."""

from __future__ import annotations

from dataclasses import dataclass

from horizon_trader.execution.broker import Order
from horizon_trader.execution.costs import ZERO_COSTS, CostModel


@dataclass(frozen=True)
class Fill:
    order: Order
    price: float
    commission: float


class PaperBroker:
    def __init__(
        self,
        cash: float,
        positions: dict[str, float] | None = None,
        costs: CostModel = ZERO_COSTS,
    ):
        self.cash = cash
        self._positions = dict(positions or {})
        self.costs = costs
        self.fills: list[Fill] = []

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices[s] for s, q in self._positions.items())

    def submit(self, order: Order, price: float) -> Fill:
        fill_price = self.costs.fill_price(order.quantity, price)
        commission = self.costs.total(order.quantity, fill_price)  # incl. exchange/regulatory
        self.cash -= order.quantity * fill_price + commission
        new_qty = self._positions.get(order.symbol, 0.0) + order.quantity
        if abs(new_qty) < 1e-9:
            self._positions.pop(order.symbol, None)
        else:
            self._positions[order.symbol] = new_qty
        fill = Fill(order, fill_price, commission)
        self.fills.append(fill)
        return fill
