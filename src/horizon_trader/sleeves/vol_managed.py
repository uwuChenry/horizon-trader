"""Position horizon: volatility-managed equity (Moreira & Muir 2017).

Holds `symbol` with weight target_vol^2 / realized variance over the past `window`
days, capped at `max_weight` (1.0 = no leverage). Exposure falls when volatility
spikes, which historically is when equity risk-adjusted returns are worst.
Rebalanced monthly, as in the paper.
"""

from __future__ import annotations

import pandas as pd

from horizon_trader.features.price import TRADING_DAYS, rebalance_monthly
from horizon_trader.sleeves.base import PanelSleeve


class VolManagedSleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        symbol: str = "SPY",
        window: int = 21,
        target_vol: float = 0.15,
        max_weight: float = 1.0,
    ):
        super().__init__(name, universe=[symbol])
        self.window = window
        self.target_vol = target_vol
        self.max_weight = max_weight

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        realized_var = px.pct_change().rolling(self.window).var() * TRADING_DAYS
        return rebalance_monthly((self.target_vol**2 / realized_var).clip(upper=self.max_weight))
