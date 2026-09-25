"""Price features on date x ticker panels. All causal: row t only uses rows <= t."""

from __future__ import annotations

import pandas as pd

TRADING_DAYS = 252


def rsi(prices: pd.DataFrame, period: int) -> pd.DataFrame:
    """Wilder's relative strength index, 0-100."""
    delta = prices.diff()
    ewm = {"alpha": 1 / period, "adjust": False, "min_periods": period}
    gain = delta.clip(lower=0).ewm(**ewm).mean()
    loss = (-delta.clip(upper=0)).ewm(**ewm).mean()
    return 100 - 100 / (1 + gain / loss)


def above_sma(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """True where price is above its simple moving average (False during warmup)."""
    return prices > prices.rolling(window).mean()


def month_starts(index: pd.DatetimeIndex) -> pd.Series:
    """True on the first trading day of each month (knowable on that day, unlike month-end)."""
    months = pd.Series(index.month, index=index)
    return months.diff().fillna(0).ne(0)


def rebalance_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Freeze daily target weights at each month start and hold them until the next one."""
    return daily.loc[month_starts(daily.index)].reindex(daily.index).ffill().fillna(0.0)
