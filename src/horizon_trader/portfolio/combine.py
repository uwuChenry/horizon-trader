from __future__ import annotations

from functools import reduce

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


def combine_history(
    histories: dict[str, pd.DataFrame], allocations: dict[str, float]
) -> pd.DataFrame:
    """Date x ticker version of `combine_sleeves`, for backtests."""
    scaled = [h * allocations[name] for name, h in histories.items()]
    return reduce(lambda a, b: a.add(b, fill_value=0.0), scaled).fillna(0.0)
