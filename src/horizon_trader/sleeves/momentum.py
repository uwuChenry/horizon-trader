"""Position horizon: cross-asset momentum rotation, rebalanced monthly.

Ranks the universe by 12-1 month return (skip the latest month, per Jegadeesh-Titman)
and holds the top_n names that also have positive momentum and trade above their
trend SMA (absolute-momentum filter, in the spirit of Antonacci's dual momentum and
Faber's GTAA). Empty slots stay in cash, which is what cuts drawdowns in bear markets.
"""

from __future__ import annotations

import pandas as pd

from horizon_trader.features.price import above_sma, rebalance_monthly
from horizon_trader.sleeves.base import PanelSleeve


class MomentumRotationSleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        lookback: int = 252,
        skip: int = 21,
        top_n: int = 3,
        trend_window: int = 200,
        universe: list[str] | None = None,
    ):
        super().__init__(name, universe)
        self.lookback = lookback
        self.skip = skip
        self.top_n = top_n
        self.trend_window = trend_window

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        momentum = px.shift(self.skip) / px.shift(self.lookback) - 1
        eligible = momentum.where((momentum > 0) & above_sma(px, self.trend_window))
        rank = eligible.rank(axis=1, ascending=False, method="first")
        return rebalance_monthly((rank <= self.top_n).astype(float) / self.top_n)
