"""Daily simulation that reuses the live execution path (compute_orders + PaperBroker).

Timing: targets decided from the close of day t are traded at the open of day t+1,
so a signal can never trade on the price that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from horizon_trader.config import ExecutionSettings
from horizon_trader.execution import CostModel, PaperBroker, compute_orders


@dataclass
class BacktestResult:
    equity: pd.Series  # marked at each close
    trades: pd.DataFrame  # date, symbol, quantity, price, commission


def _row_prices(row: pd.Series) -> dict[str, float]:
    return row.dropna().to_dict()


def simulate(
    targets: pd.DataFrame,
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    starting_cash: float,
    execution: ExecutionSettings,
    costs: CostModel,
) -> BacktestResult:
    closes = closes.ffill()
    # Trade at the open; fall back to the prior close if a symbol has no open that day.
    trade_px = opens.reindex_like(closes).fillna(closes.shift(1))
    targets = targets.reindex(index=closes.index).fillna(0.0)

    broker = PaperBroker(cash=starting_cash, costs=costs)
    equity: dict[pd.Timestamp, float] = {}
    trades: list[tuple] = []
    for i, day in enumerate(closes.index):
        if i > 0:
            px = _row_prices(trade_px.iloc[i])
            wanted = targets.iloc[i - 1]
            wanted = wanted[(wanted != 0) & wanted.index.isin(list(px))]
            orders = compute_orders(wanted, broker.positions(), px, broker.equity(px), execution)
            for order in orders:
                fill = broker.submit(order, px[order.symbol])
                trades.append((day, order.symbol, order.quantity, fill.price, fill.commission))
        equity[day] = broker.equity(_row_prices(closes.iloc[i]))

    return BacktestResult(
        equity=pd.Series(equity, name="equity"),
        trades=pd.DataFrame(trades, columns=["date", "symbol", "quantity", "price", "commission"]),
    )
