"""Cross-sectional stock selection from any DSL alpha formula.

Holds the top_n names by `direction * formula`, equal weight, rebalanced at the
start of each month or week. This is the bridge from a researched alpha to a
sleeve the backtester, robustness harness, and daily run all understand.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

import pandas as pd

from horizon_trader.alphas.dsl import evaluate, fields_used, fill_params
from horizon_trader.features.price import rebalance_at
from horizon_trader.sleeves.base import PanelSleeve

BarsLoader = Callable[[list[str]], dict[str, pd.DataFrame]]


def _default_loader(symbols: list[str]) -> dict[str, pd.DataFrame]:
    from horizon_trader.data.store import load_bars

    return load_bars(symbols)


class AlphaSleeve(PanelSleeve):
    def __init__(
        self,
        name: str,
        formula: str,
        direction: Literal[1, -1] = 1,
        formula_params: dict[str, int] | None = None,
        top_n: int = 5,
        rebalance: Literal["monthly", "weekly"] = "monthly",
        universe: list[str] | None = None,
        bars_loader: BarsLoader = _default_loader,
    ):
        super().__init__(name, universe)
        self.formula = fill_params(formula, formula_params)
        self.direction = direction
        self.top_n = top_n
        self.freq = {"monthly": "M", "weekly": "W"}[rebalance]
        self.bars_loader = bars_loader

    def _bars(self, closes: pd.DataFrame) -> dict[str, pd.DataFrame]:
        if fields_used(self.formula) <= {"CLOSE", "RETURNS"}:
            return {"close": closes}
        # Other fields come from the bar store, cut to the rows we were given so a
        # truncated price history (live run, lookahead tests) can't see later bars.
        bars = self.bars_loader(list(closes.columns))
        return {k: v.reindex(index=closes.index, columns=closes.columns) for k, v in bars.items()}

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        px = self._select(prices)
        score = evaluate(self.formula, self._bars(px)) * self.direction
        rank = score.where(px.notna()).rank(axis=1, ascending=False, method="first")
        return rebalance_at((rank <= self.top_n).astype(float) / self.top_n, self.freq)
