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

    Symbols held but absent from `targets` are sold down to zero. Resizing an
    existing position only happens once it has drifted more than
    `rebalance_band` from target (opening and fully closing always go through),
    and trades smaller than `min_trade_value` are skipped. Both keep a small
    account from bleeding commissions on noise. Sells come first so they free up
    cash for the buys.
    """
    orders: list[Order] = []
    for symbol in sorted(set(targets.index) | set(positions)):
        if symbol not in prices:
            raise KeyError(f"no price for {symbol}")
        price = prices[symbol]
        target_w = targets.get(symbol, 0.0)
        held = positions.get(symbol, 0.0)
        opening_or_closing = (held == 0) != (target_w == 0)
        if (
            not opening_or_closing
            and abs(target_w - held * price / equity) < settings.rebalance_band
        ):
            continue
        delta = round(target_w * equity / price - held, settings.share_decimals)
        if abs(delta * price) >= settings.min_trade_value:
            orders.append(Order(symbol=symbol, quantity=delta))
    return sorted(orders, key=lambda o: o.quantity)
