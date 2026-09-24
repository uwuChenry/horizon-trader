"""Fixed-weight sleeve: a placeholder and a useful benchmark (e.g. 60/40)."""

from __future__ import annotations

from datetime import date

import pandas as pd


class StaticSleeve:
    def __init__(self, name: str, weights: dict[str, float]):
        self.name = name
        self._weights = pd.Series(weights, dtype=float)

    def target_weights(self, asof: date, prices: pd.DataFrame) -> pd.Series:
        return self._weights.copy()
