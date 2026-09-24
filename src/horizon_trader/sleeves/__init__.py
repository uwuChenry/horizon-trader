"""Strategy sleeves. Register new sleeve types in SLEEVE_TYPES so config can build them."""

from __future__ import annotations

from horizon_trader.config import SleeveSettings
from horizon_trader.sleeves.base import Sleeve
from horizon_trader.sleeves.static import StaticSleeve

SLEEVE_TYPES = {
    "static": StaticSleeve,
}


def build_sleeve(name: str, cfg: SleeveSettings) -> Sleeve:
    try:
        cls = SLEEVE_TYPES[cfg.type]
    except KeyError:
        raise ValueError(f"unknown sleeve type {cfg.type!r} for sleeve {name!r}") from None
    return cls(name=name, **cfg.params)


__all__ = ["SLEEVE_TYPES", "Sleeve", "build_sleeve"]
