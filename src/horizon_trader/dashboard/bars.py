"""Price bars around one backtest trade, from local caches only (never a network call)."""

from __future__ import annotations

import pandas as pd

from horizon_trader.config import data_dir


def trade_bars(trade: pd.Series, chart: str | None) -> pd.DataFrame:
    """The session's minute bars for intraday ("massive_minute") runs, +/- 40 days of daily
    bars otherwise. Indexed by time; empty if nothing is cached."""
    entry = pd.Timestamp(trade["entry_time"])
    if chart == "massive_minute":
        from horizon_trader.datasources import massive

        day = entry.tz_convert(massive.TZ).date() if entry.tzinfo else entry.date()
        if not massive.local_path("minute", day).exists():
            return pd.DataFrame()
        bars = massive.load_day(day, "minute", [trade["symbol"]])
        start = pd.Timestamp.combine(day, pd.Timestamp("09:30").time()).tz_localize(massive.TZ)
        bars = bars[(bars["ts"] >= start) & (bars["ts"] < start + pd.Timedelta(hours=6.5))]
        return bars.set_index("ts")
    path = data_dir() / "bars" / f"{trade['symbol']}.parquet"
    if not path.exists():
        return pd.DataFrame()
    bars = pd.read_parquet(path)
    pad = pd.Timedelta(days=40)
    return bars.loc[entry - pad : pd.Timestamp(trade["exit_time"]) + pad]
