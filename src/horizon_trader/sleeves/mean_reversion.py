"""Swing horizon: buy short-term oversold dips inside long-term uptrends (Connors RSI(2) style).

Enter when RSI(rsi_period) < entry and price is above its trend SMA. Exit when
RSI > exit, the trend breaks, or after max_hold days (a time stop; the name can
re-enter the next day if it is still oversold). Each position gets
1/max_positions of the sleeve; if more names qualify than there are slots, the
most oversold ones win.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.features.price import above_sma, rsi
from horizon_trader.sleeves.base import PanelSleeve


class MeanReversionSleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        rsi_period: int = 2,
        entry: float = 10.0,
        exit: float = 70.0,
        trend_window: int = 200,
        max_positions: int = 3,
        max_hold: int = 10,
        universe: list[str] | None = None,
    ):
        super().__init__(name, universe)
        self.rsi_period = rsi_period
        self.entry = entry
        self.exit = exit
        self.trend_window = trend_window
        self.max_positions = max_positions
        self.max_hold = max_hold

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        strength = rsi(px, self.rsi_period)
        uptrend = above_sma(px, self.trend_window)
        enter = ((strength < self.entry) & uptrend).to_numpy()
        leave = ((strength > self.exit) | ~uptrend).to_numpy()

        # Entry/exit state is path dependent, so walk forward one day at a time.
        held = np.zeros(px.shape, dtype=bool)
        days_held = np.zeros(px.shape[1], dtype=int)
        for t in range(len(px)):
            was_held = held[t - 1] if t else np.zeros(px.shape[1], dtype=bool)
            stay = was_held & ~leave[t] & (days_held < self.max_hold)
            held[t] = stay | (~was_held & enter[t])
            days_held = np.where(held[t], days_held + 1, 0)

        held_rsi = strength.where(pd.DataFrame(held, index=px.index, columns=px.columns))
        slot = held_rsi.rank(axis=1, method="first")
        return (slot <= self.max_positions).astype(float) / self.max_positions
