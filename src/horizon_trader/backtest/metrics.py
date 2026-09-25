from __future__ import annotations

import numpy as np
import pandas as pd

from horizon_trader.features.price import TRADING_DAYS


def max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1).min())


def sharpe(equity: pd.Series) -> float:
    """Annualized Sharpe of daily returns at a 0% risk-free rate."""
    returns = equity.pct_change().dropna()
    std = returns.std()
    return float(returns.mean() / std * np.sqrt(TRADING_DAYS)) if std else np.nan


def summarize(equity: pd.Series, trades: pd.DataFrame | None = None) -> dict[str, float]:
    """Headline stats. Sharpe uses a 0% risk-free rate, so it's flattering in high-rate years."""
    returns = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    vol = returns.std() * np.sqrt(TRADING_DAYS)
    mdd = max_drawdown(equity)
    stats = {
        "CAGR": cagr,
        "vol": vol,
        "Sharpe": sharpe(equity),
        "max DD": mdd,
        "Calmar": cagr / abs(mdd) if mdd else np.nan,
        "final": float(equity.iloc[-1]),
    }
    if trades is not None:
        traded = (trades["quantity"].abs() * trades["price"]).sum()
        stats["turnover/yr"] = traded / equity.mean() / years
        stats["trades/yr"] = len(trades) / years
        stats["commissions"] = float(trades["commission"].sum())
    return stats
