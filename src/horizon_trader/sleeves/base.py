"""The Sleeve contract: every strategy, whatever its horizon, outputs target weights."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class Sleeve(Protocol):
    name: str

    def target_weights(self, asof: date, prices: pd.DataFrame) -> pd.Series:
        """Return {ticker: weight} as a fraction of this sleeve's capital.

        `prices` is a date x ticker panel of adjusted closes containing only data
        available at `asof` (no lookahead). Gross weight should be <= 1.0.
        """
        ...
