"""The Broker contract, implemented by IBKR, the paper simulator, and any future engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Order:
    symbol: str
    quantity: float  # signed: + buy, - sell (fractional allowed)
    order_type: Literal["MKT", "LMT"] = "MKT"
    limit_price: float | None = None


class Broker(Protocol):
    def positions(self) -> dict[str, float]:
        """Current holdings in shares, keyed by symbol."""
        ...

    def equity(self, prices: dict[str, float]) -> float:
        """Net liquidation value."""
        ...

    def submit(self, order: Order, price: float) -> None: ...
