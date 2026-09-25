"""Measure how well an alpha ranks stocks by their future returns.

Core metric is the daily rank Information Coefficient (IC): the Spearman correlation,
across stocks, between today's alpha and the next h days' return. For a single
factor in large caps, a mean IC of 0.01-0.03 with a stable sign is genuinely useful;
anything above ~0.05 deserves suspicion before celebration.

Forward returns are the only place the future is touched, and only as the label.
Research-period labels are computed from prices cut off at the holdout start, so
no research number peeks into the holdout.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.alphas.dsl import evaluate
from horizon_trader.alphas.library import AlphaLibrary
from horizon_trader.features.price import TRADING_DAYS

HORIZONS = (1, 5, 21)
MIN_NAMES = 20


def forward_returns(close: pd.DataFrame, horizon: int) -> pd.DataFrame:
    return close.shift(-horizon) / close - 1


def rank_ic(alpha: pd.DataFrame, fwd: pd.DataFrame, min_names: int = MIN_NAMES) -> pd.Series:
    """Per-day Spearman correlation across stocks (NaN on days with too few names)."""
    alpha, fwd = alpha.align(fwd, join="inner")
    valid = alpha.notna() & fwd.notna()
    a = alpha.where(valid).rank(axis=1)
    f = fwd.where(valid).rank(axis=1)
    a = a.sub(a.mean(axis=1), axis=0)
    f = f.sub(f.mean(axis=1), axis=0)
    ic = (a * f).sum(axis=1) / np.sqrt((a**2).sum(axis=1) * (f**2).sum(axis=1))
    return ic.where(valid.sum(axis=1) >= min_names).dropna()


def quantile_spread(alpha: pd.DataFrame, fwd: pd.DataFrame, quantiles: int = 5) -> pd.Series:
    """Per-day mean forward return of the top quantile minus the bottom quantile."""
    alpha, fwd = alpha.align(fwd, join="inner")
    pct = alpha.where(fwd.notna()).rank(axis=1, pct=True)
    top = fwd.where(pct > 1 - 1 / quantiles).mean(axis=1)
    bottom = fwd.where(pct <= 1 / quantiles).mean(axis=1)
    return (top - bottom).dropna()


def top_turnover(alpha: pd.DataFrame, quantiles: int = 5) -> float:
    """Average share of top-quantile names that change from one day to the next."""
    top = alpha.rank(axis=1, pct=True) > 1 - 1 / quantiles
    kept = (top & top.shift(1, fill_value=False)).sum(axis=1)
    size = top.sum(axis=1)
    return float((1 - kept / size.where(size > 0)).iloc[1:].mean())


def _tstat(ic: pd.Series, horizon: int) -> float:
    """t-stat of mean IC, deflating the sample size for overlapping h-day labels."""
    effective_n = len(ic) / horizon
    return float(ic.mean() / ic.std() * np.sqrt(effective_n)) if len(ic) > 2 else np.nan


def ic_summary(alpha: pd.DataFrame, close: pd.DataFrame, horizon: int) -> dict[str, float]:
    row: dict[str, float] = {}
    for h in HORIZONS:
        row[f"IC {h}d"] = rank_ic(alpha, forward_returns(close, h)).mean()
    fwd = forward_returns(close, horizon)
    ic = rank_ic(alpha, fwd)
    half = len(ic) // 2
    row[f"t({horizon}d)"] = _tstat(ic, horizon)
    row["IC>0 %"] = float((ic > 0).mean())
    row["IC 1st half"] = ic.iloc[:half].mean()
    row["IC 2nd half"] = ic.iloc[half:].mean()
    row["Q5-Q1 /yr"] = quantile_spread(alpha, fwd).mean() * TRADING_DAYS / horizon
    row["top turnover/day"] = top_turnover(alpha)
    return row


def evaluate_library(
    library: AlphaLibrary,
    bars: dict[str, pd.DataFrame],
    start: str,
    holdout_start: str,
    horizon: int = 5,
    holdout: bool = False,
) -> pd.DataFrame:
    """One row per alpha variant: research-period stats, or holdout stats if `holdout`."""
    close = bars["close"]
    cutoff = pd.Timestamp(holdout_start)
    if holdout:
        label_close, window = close, slice(cutoff, None)
    else:
        label_close = close.loc[close.index < cutoff]
        window = slice(pd.Timestamp(start), cutoff - pd.Timedelta(days=1))

    rows = {}
    for spec in library.alphas:
        for params, formula in spec.variants():
            # Signals use full history (they're causal); only the evaluation window is cut.
            alpha = (evaluate(formula, bars) * spec.direction).loc[window]
            rows[spec.label(params)] = ic_summary(alpha, label_close.loc[window], horizon)
    return pd.DataFrame(rows).T
