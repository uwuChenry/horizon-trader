from __future__ import annotations

import pandas as pd

from horizon_trader.config import RiskSettings


def apply_risk_limits[T: (pd.Series, pd.DataFrame)](weights: T, risk: RiskSettings) -> T:
    """Clip each position to +/- max_weight, then scale down if gross exposure exceeds max_gross.

    Accepts one day's weights (Series) or a date x ticker history (DataFrame, row-wise).
    """
    capped = weights.clip(lower=-risk.max_weight, upper=risk.max_weight)
    if isinstance(capped, pd.DataFrame):
        scale = (risk.max_gross / capped.abs().sum(axis=1)).clip(upper=1.0)
        return capped.mul(scale, axis=0)
    gross = capped.abs().sum()
    if gross > risk.max_gross:
        capped = capped * (risk.max_gross / gross)
    return capped
