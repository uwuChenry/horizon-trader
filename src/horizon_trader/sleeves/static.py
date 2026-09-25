"""Fixed-weight sleeve: a placeholder and a useful benchmark (e.g. 60/40, SPY buy-and-hold)."""

from __future__ import annotations

import pandas as pd

from horizon_trader.sleeves.base import PanelSleeve


class StaticSleeve(PanelSleeve):
    def __init__(self, name: str, weights: dict[str, float]):
        super().__init__(name)
        self._weights = pd.Series(weights, dtype=float)

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        listed = prices.reindex(columns=self._weights.index).notna()
        return listed.astype(float) * self._weights
