from __future__ import annotations

import pandas as pd

from horizon_trader.config import RiskSettings


def apply_risk_limits(weights: pd.Series, risk: RiskSettings) -> pd.Series:
    """Clip each position to +/- max_weight, then scale down if gross exposure exceeds max_gross."""
    capped = weights.clip(lower=-risk.max_weight, upper=risk.max_weight)
    gross = capped.abs().sum()
    if gross > risk.max_gross:
        capped = capped * (risk.max_gross / gross)
    return capped
