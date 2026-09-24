from __future__ import annotations

import pandas as pd


def combine_sleeves(
    sleeve_weights: dict[str, pd.Series], allocations: dict[str, float]
) -> pd.Series:
    """Scale each sleeve's weights by its allocation and net them per ticker.

    A long in one sleeve and a short in another offset here, so execution only
    ever trades the net position.
    """
    scaled = [w * allocations[name] for name, w in sleeve_weights.items() if not w.empty]
    if not scaled:
        return pd.Series(dtype=float)
    net = pd.concat(scaled, axis=1).fillna(0.0).sum(axis=1)
    return net[net != 0.0].sort_index()
