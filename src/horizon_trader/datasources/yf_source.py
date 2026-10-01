"""yfinance prototype source. Survivorship-biased (no delisted tickers): fine for ETFs and
prototyping, not for stock-universe backtests. Swap for Norgate later."""

from __future__ import annotations

import logging

import pandas as pd
import yfinance as yf

from horizon_trader.config import data_dir

log = logging.getLogger(__name__)

# Keep yfinance's sqlite caches inside our data dir instead of the shared per-user folder.
yf.set_tz_cache_location(str(data_dir() / "yfinance-cache"))


def _download(symbols: list[str], **kwargs) -> pd.DataFrame:
    # threads=False: parallel downloads contend on yfinance's sqlite cache ("database is locked").
    return yf.download(symbols, auto_adjust=True, progress=False, threads=False, **kwargs)


def _field(raw: pd.DataFrame, field: str, symbol: str) -> pd.Series:
    if isinstance(raw.columns, pd.MultiIndex):
        return raw[field][symbol]
    return raw[field]


def fetch_closes(symbols: list[str], period: str = "2y") -> pd.DataFrame:
    """Date x ticker panel of split/dividend-adjusted closes."""
    raw = _download(symbols, period=period)
    closes = pd.DataFrame({s: _field(raw, "Close", s) for s in symbols})
    closes = closes.dropna(axis=1, how="all").dropna(how="all")
    if missing := sorted(set(symbols) - set(closes.columns)):
        log.warning("no price data for %s", missing)
    return closes


FIELDS = ("Open", "High", "Low", "Close", "Volume")


def fetch_bars(symbols: list[str]) -> dict[str, pd.DataFrame]:
    """Full adjusted daily OHLCV history per symbol (lowercase column names)."""
    raw = _download(symbols, period="max")
    bars = {}
    for s in symbols:
        df = pd.DataFrame({f.lower(): _field(raw, f, s) for f in FIELDS})
        df = df.dropna(subset=["close"])
        if df.empty:
            log.warning("no price data for %s", s)
            continue
        bars[s] = df
    return bars
