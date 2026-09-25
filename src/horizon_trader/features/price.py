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


def period_starts(index: pd.DatetimeIndex, freq: str) -> pd.Series:
    """True on the first trading day of each period ("M" month, "W" week).

    Knowable on that day, unlike period-end. The very first row is never a start,
    since there's no prior row to compare against.
    """
    periods = pd.Series(index.to_period(freq), index=index)
    previous = periods.shift()
    return periods.ne(previous) & previous.notna()


def month_starts(index: pd.DatetimeIndex) -> pd.Series:
    return period_starts(index, "M")


def rebalance_at(daily: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Freeze daily target weights at each period start and hold them until the next one."""
    return daily.loc[period_starts(daily.index, freq)].reindex(daily.index).ffill().fillna(0.0)


def rebalance_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    return rebalance_at(daily, "M")
