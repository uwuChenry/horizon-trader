"""Strategy sleeves. Register new sleeve types in SLEEVE_TYPES so config can build them."""

from __future__ import annotations

from horizon_trader.config import SleeveSettings
from horizon_trader.sleeves.base import PanelSleeve, Sleeve
from horizon_trader.sleeves.macd import MacdSleeve
from horizon_trader.sleeves.mean_reversion import MeanReversionSleeve
from horizon_trader.sleeves.momentum import MomentumRotationSleeve
from horizon_trader.sleeves.static import StaticSleeve
from horizon_trader.sleeves.trend import TrendFollowingSleeve
from horizon_trader.sleeves.vol_managed import VolManagedSleeve

SLEEVE_TYPES = {
    "static": StaticSleeve,
    "momentum_rotation": MomentumRotationSleeve,
    "mean_reversion": MeanReversionSleeve,
    "trend_following": TrendFollowingSleeve,
    "vol_managed": VolManagedSleeve,
    "macd": MacdSleeve,
}


def build_sleeve(name: str, cfg: SleeveSettings) -> Sleeve:
    try:
        cls = SLEEVE_TYPES[cfg.type]
    except KeyError:
        raise ValueError(f"unknown sleeve type {cfg.type!r} for sleeve {name!r}") from None
    return cls(name=name, **cfg.params)


__all__ = ["SLEEVE_TYPES", "PanelSleeve", "Sleeve", "build_sleeve"]
