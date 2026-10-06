"""Frozen ETF hypotheses for the October 2026 research cycle; no live registration.

The public sleeve contract is causal close-time weights. ``decision_history``
keeps only monthly decisions so the research account holds shares between them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.features.price import TRADING_DAYS, month_starts
from horizon_trader.sleeves.base import PanelSleeve


class ResearchCycleSleeve(PanelSleeve):
    def __init__(self, name: str, family: str, **params):
        super().__init__(name, universe=["QQQ", "GLD", "IEF"])
        self.family = family
        self.params = params

    def daily_signal(self, prices: pd.DataFrame) -> pd.DataFrame:
        """All calculations at row t use only observations through close t."""
        p, family = self.params, self.family
        weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        qqq = prices["QQQ"]
        if family in {"buy_hold", "static"}:
            weights["QQQ"] = p.get("weight", 1.0)
        elif family == "equal_weight":
            weights.loc[:, ["QQQ", "GLD", "IEF"]] = 1 / 3
        elif family in {"trend", "voltrend", "vol_only"}:
            signal = pd.Series(1.0, index=prices.index)
            if family != "vol_only":
                signal = (qqq > qqq.rolling(p["trend"]).mean()).astype(float)
            if family != "trend":
                vol = qqq.pct_change(fill_method=None).rolling(p["vol_window"]).std()
                vol = vol * np.sqrt(TRADING_DAYS)
                signal *= (p["target_vol"] / vol).clip(upper=p["cap"]).fillna(0)
            weights["QQQ"] = signal
        elif family == "rotation":
            assets = prices[["QQQ", "GLD", "IEF"]]
            mom = assets.shift(p["skip"]) / assets.shift(p["lookback"]) - 1
            eligible = mom.where((mom > 0) & (assets > assets.rolling(p["trend"]).mean()))
            ranks = eligible.rank(axis=1, ascending=False, method="first")
            weights.loc[:, assets.columns] = (ranks == 1).astype(float)
        else:
            raise ValueError(f"Unknown research family: {family}")
        return weights

    def weights_history(self, prices: pd.DataFrame) -> pd.DataFrame:
        daily = self.daily_signal(prices)
        return daily.where(month_starts(prices.index), axis=0).ffill().fillna(0)

    def decision_history(self, prices: pd.DataFrame, start: str) -> pd.DataFrame:
        """Monthly close decisions plus an initial decision using available history.

        ``start`` is the cash-only initial NAV session. First trade is later.
        Indicators must be warmed before slicing. Buy/hold makes one decision.
        """
        daily = self.daily_signal(prices)
        mask = month_starts(prices.index)
        decisions = daily.where(mask, axis=0).loc[start:].copy()
        if decisions.empty:
            raise ValueError("No sessions at or after start")
        decisions.iloc[0] = daily.loc[decisions.index[0]]
        if self.family == "buy_hold":
            decisions.iloc[1:] = np.nan
        return decisions


def build_cycle_sleeve(spec: dict) -> ResearchCycleSleeve:
    return ResearchCycleSleeve(**{k: v for k, v in spec.items() if k != "central"})
