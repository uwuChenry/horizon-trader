"""Swing horizon: classic MACD crossover (Appel), the TradingView staple, as a baseline.

Long a name while its MACD line (EMA(fast) - EMA(slow)) is above its signal line
(EMA of MACD); flat otherwise. Optional trend filter: only long above the trend SMA.
Each name gets an equal 1/N slice of the sleeve. Daily bars, so holds last days-weeks.
"""

from __future__ import annotations

import pandas as pd

from horizon_trader.features.price import above_sma
from horizon_trader.sleeves.base import PanelSleeve


def _ema(df: pd.DataFrame, span: int) -> pd.DataFrame:
    return df.ewm(span=span, adjust=False, min_periods=span).mean()


class MacdSleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        trend_window: int | None = None,
        universe: list[str] | None = None,
    ):
        super().__init__(name, universe)
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.trend_window = trend_window

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        macd = _ema(px, self.fast) - _ema(px, self.slow)
        long = macd > _ema(macd, self.signal)
        if self.trend_window:
            long &= above_sma(px, self.trend_window)
        return long.astype(float) / px.shape[1]
