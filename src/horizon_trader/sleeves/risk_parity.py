"""Position horizon: unlevered risk parity (Asness, Frazzini & Pedersen 2012, "Leverage
Aversion and Risk Parity", Financial Analysts Journal).

Each asset gets weight proportional to 1 / its trailing volatility, so a bond ETF with a
third of the stock market's volatility gets three times the dollars. The paper estimates
volatility over a rolling 3-year window (756 trading days here) and then levers the whole
portfolio to 10% volatility. A $5k Reg T account with the book's 1.0 gross cap can't lever,
so this version stays fully invested at whatever volatility the mix has (typically lower
than stocks, with lower return). Unlike the trend sleeve nothing is ever sold for being
in a downtrend: 2022, when stocks and bonds fell together, is its known stress test.
Rebalanced monthly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.features.price import rebalance_monthly
from horizon_trader.sleeves.base import PanelSleeve

DEFAULT_UNIVERSE = ["SPY", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC"]


class RiskParitySleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        vol_window: int = 756,
        universe: list[str] | None = None,
    ):
        super().__init__(name, universe or DEFAULT_UNIVERSE)
        self.vol_window = vol_window

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        vol = px.pct_change(fill_method=None).rolling(self.vol_window).std()
        inv_vol = (1 / vol).replace(np.inf, np.nan)
        # an asset joins once it has a full window; until every asset does, the ones
        # that have one share the budget
        weights = inv_vol.div(inv_vol.sum(axis=1), axis=0)
        return rebalance_monthly(weights.fillna(0.0))
