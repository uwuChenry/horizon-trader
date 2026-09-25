"""The Sleeve contract: every strategy, whatever its horizon, outputs target weights."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class Sleeve(Protocol):
    name: str

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Date x ticker target weights as a fraction of this sleeve's capital.

        `prices` is a date x ticker panel of adjusted closes. Row t must only use
        prices up to t (no lookahead). Gross weight per row should be <= 1.0.
        """
        ...

    def target_weights(self, asof: date, prices: pd.DataFrame) -> pd.Series:
        """Today's {ticker: weight}, nonzero entries only."""
        ...


class PanelSleeve:
    """Base for sleeves defined on the whole price panel.

    Live weights are the last row of `weights_history`, so the backtest and the
    daily run go through exactly the same code.
    """

    def __init__(self, name: str, universe: list[str] | None = None):
        self.name = name
        self.universe = universe

    def _select(self, prices: pd.DataFrame) -> pd.DataFrame:
        if self.universe is None:
            return prices
        return prices[[s for s in self.universe if s in prices.columns]]

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError

    def target_weights(self, asof: date, prices: pd.DataFrame) -> pd.Series:
        history = self.weights_history(prices.loc[:asof])
        if history.empty:
            return pd.Series(dtype=float)
        last = history.iloc[-1]
        return last[last != 0]
