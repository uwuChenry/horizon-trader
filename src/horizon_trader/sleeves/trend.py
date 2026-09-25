"""Position horizon: time-series momentum / trend following (Moskowitz, Ooi & Pedersen 2012).

Long-only version for a small cash account: each asset is held only while its
trailing `lookback` return is positive. Every asset gets an inverse-volatility
risk budget computed across the whole universe, so an asset in a downtrend leaves
its budget in cash rather than handing it to the others. Unlike the momentum
rotation sleeve, nothing is ranked: every uptrending asset is owned. Rebalanced monthly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.features.price import rebalance_monthly
from horizon_trader.sleeves.base import PanelSleeve


class TrendFollowingSleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        lookback: int = 252,
        vol_window: int = 63,
        universe: list[str] | None = None,
    ):
        super().__init__(name, universe)
        self.lookback = lookback
        self.vol_window = vol_window

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        uptrend = px / px.shift(self.lookback) - 1 > 0
        vol = px.pct_change().rolling(self.vol_window).std()
        inv_vol = (1 / vol).replace(np.inf, np.nan)
        budget = inv_vol.div(inv_vol.sum(axis=1), axis=0)
        return rebalance_monthly(budget.where(uptrend, 0.0).fillna(0.0))
