"""Daily and opening-range features for intraday strategies, from unadjusted Massive bars.

Everything is split-safe: history is converted to today's share basis before averaging, so a
10-for-1 split neither inflates relative volume 10x nor shrinks the ATR. Row t of every output
uses only data known at 9:30 + n minutes on day t (daily stats come from days < t).
"""

from __future__ import annotations

from datetime import date, time

import numpy as np
import pandas as pd

from horizon_trader.data import massive

TZ = massive.TZ
OPEN = time(9, 30)
DAILY_FIELDS = ("open", "high", "low", "close", "volume")


def session_open(day: date) -> pd.Timestamp:
    return pd.Timestamp.combine(day, OPEN).tz_localize(TZ)


def load_daily_panels(days: list[date], tickers: set[str]) -> dict[str, pd.DataFrame]:
    """Unadjusted daily OHLCV, date x ticker, for the given tickers."""
    frames = []
    for d in days:
        df = massive.load_day(d, "day", sorted(tickers))
        frames.append(df.assign(date=pd.Timestamp(d))[["date", "ticker", *DAILY_FIELDS]])
    long = pd.concat(frames).drop_duplicates(["date", "ticker"], keep="last")
    return {f: long.pivot(index="date", columns="ticker", values=f) for f in DAILY_FIELDS}


def split_factors(index: pd.DatetimeIndex, columns: pd.Index, splits: pd.DataFrame) -> pd.DataFrame:
    """Multiplier taking an unadjusted price on each date to the latest share basis.

    Volume converts the other way (divide). Only ratios of factors are ever used, so splits
    after a date cancel out and nothing leaks from the future.
    """
    factor = np.ones((len(index), len(columns)))
    col = {t: i for i, t in enumerate(columns)}
    for ev in splits[splits["ticker"].isin(col)].itertuples():
        if ev.split_to > 0 and ev.split_from > 0:
            before = index.searchsorted(ev.execution_date)  # rows strictly before execution
            factor[:before, col[ev.ticker]] *= ev.split_from / ev.split_to
    return pd.DataFrame(factor, index=index, columns=columns)


def daily_features(
    panels: dict[str, pd.DataFrame], factor: pd.DataFrame, lookback: int = 14
) -> dict[str, pd.DataFrame]:
    """Per date x ticker, in that date's own (unadjusted) share basis:

    open        today's open (known at 9:30)
    close       today's official close (for exits only, never for signals)
    atr         mean true range of the previous `lookback` days
    avg_volume  mean daily volume of the previous `lookback` days
    prev_close  yesterday's close
    """
    high, low, close = (panels[f] * factor for f in ("high", "low", "close"))
    volume = panels["volume"] / factor
    prev = close.shift(1)
    # fmax ignores a missing previous close, falling back to high - low
    tr = np.fmax(np.fmax(high - low, (high - prev).abs()), (low - prev).abs()).where(high.notna())

    def trailing_mean(x: pd.DataFrame) -> pd.DataFrame:
        return x.rolling(lookback, min_periods=lookback).mean().shift(1)

    return {
        "open": panels["open"],
        "close": panels["close"],
        "atr": trailing_mean(tr) / factor,
        "avg_volume": trailing_mean(volume) * factor,
        "prev_close": prev / factor,
    }


def opening_range(minute: pd.DataFrame, day: date, minutes: int = 5) -> pd.DataFrame:
    """OHLCV of the first `minutes` of the regular session, one row per ticker.

    `opens_on_time` is False when the ticker's first bar came after 9:30 (its open is then
    not the session open, so it isn't tradeable, but its volume still counts for history).
    """
    start = session_open(day)
    bars = minute[(minute["ts"] >= start) & (minute["ts"] < start + pd.Timedelta(minutes=minutes))]
    g = bars.groupby("ticker", sort=True)
    out = pd.DataFrame(
        {
            "or_open": g["open"].first(),
            "or_high": g["high"].max(),
            "or_low": g["low"].min(),
            "or_close": g["close"].last(),
            "or_volume": g["volume"].sum(),
            "opens_on_time": g["ts"].first() == start,
        }
    )
    out.index.name = "ticker"
    return out


def relative_volume(
    or_volume: pd.DataFrame, factor: pd.DataFrame, traded: pd.DataFrame, lookback: int = 14
) -> pd.DataFrame:
    """Opening-range volume / its mean over the previous `lookback` days (same share basis).

    A day the stock traded but not in the opening range counts as zero volume.
    """
    vol = (or_volume.reindex_like(factor).fillna(0.0) / factor).where(traded)
    hist = vol.rolling(lookback, min_periods=lookback).mean().shift(1)
    return vol / hist.where(hist > 0)


def volatility_regime(close: pd.Series, window: int = 20, lookback: int = 252) -> pd.Series:
    """+1 on days the market's realized volatility is above its own median, -1 below.

    Volatility = std of daily returns over `window` days through YESTERDAY; the median is over
    the previous `lookback` days of that series. So day t's regime is known at its open. NaN
    until there is enough history.
    """
    vol = close.pct_change().rolling(window, min_periods=window).std().shift(1)
    med = vol.rolling(lookback, min_periods=lookback).median()
    return np.sign(vol - med).where(med.notna())
