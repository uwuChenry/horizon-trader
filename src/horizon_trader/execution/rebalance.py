from __future__ import annotations

import pandas as pd

from horizon_trader.config import ExecutionSettings
from horizon_trader.execution.broker import Order


def compute_orders(
    targets: pd.Series,
    positions: dict[str, float],
    prices: dict[str, float],
    equity: float,
    settings: ExecutionSettings,
) -> list[Order]:
    """Turn target weights into the orders that move current positions to target.

    Symbols held but absent from `targets` are sold down to zero. Trades smaller
    than `min_trade_value` are skipped to avoid paying commissions on dust.
    Sells come first so they free up cash for the buys.
    """
    orders: list[Order] = []
    for symbol in sorted(set(targets.index) | set(positions)):
        if symbol not in prices:
            raise KeyError(f"no price for {symbol}")
        target_qty = targets.get(symbol, 0.0) * equity / prices[symbol]
        delta = round(target_qty - positions.get(symbol, 0.0), settings.share_decimals)
        if abs(delta * prices[symbol]) >= settings.min_trade_value:
            orders.append(Order(symbol=symbol, quantity=delta))
    return sorted(orders, key=lambda o: o.quantity)
