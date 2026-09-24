"""In-memory broker for dry runs and tests. Fills immediately at the given price, no costs."""

from __future__ import annotations

from horizon_trader.execution.broker import Order


class PaperBroker:
    def __init__(self, cash: float, positions: dict[str, float] | None = None):
        self.cash = cash
        self._positions = dict(positions or {})
        self.fills: list[tuple[Order, float]] = []

    def positions(self) -> dict[str, float]:
        return dict(self._positions)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices[s] for s, q in self._positions.items())

    def submit(self, order: Order, price: float) -> None:
        self.cash -= order.quantity * price
        new_qty = self._positions.get(order.symbol, 0.0) + order.quantity
        if abs(new_qty) < 1e-9:
            self._positions.pop(order.symbol, None)
        else:
            self._positions[order.symbol] = new_qty
        self.fills.append((order, price))
