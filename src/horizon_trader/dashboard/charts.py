"""Plotly figure builders for the dashboard, kept out of app.py so they can be tested directly."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from horizon_trader.config import data_dir

# Validated categorical order (dataviz palette), a blue/red diverging pair for win/loss
# polarity, and hairline chrome.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
WIN, LOSS, NEUTRAL = "#2a78d6", "#e34948", "#898781"
GRID = "rgba(137,135,129,0.25)"
DIVERGING = [[0.0, LOSS], [0.5, "#f0efec"], [1.0, WIN]]


def style(fig: go.Figure, height: int = 360, **kw) -> go.Figure:
    """Shared chart chrome; keyword arguments override the defaults."""
    defaults = dict(
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
        legend=dict(orientation="h", y=1.08, x=0),
    )
    fig.update_layout(**(defaults | kw))
    fig.update_xaxes(showgrid=False, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID)
    return fig


def trade_bars(trade: pd.Series, chart: str | None) -> pd.DataFrame:
    """Price bars around one trade from local data: the session's minute bars for intraday
    ("massive_minute") runs, +/- 40 days of daily bars otherwise. Empty if nothing is cached."""
    entry = pd.Timestamp(trade["entry_time"])
    if chart == "massive_minute":
        from horizon_trader.data import massive

        day = entry.tz_convert(massive.TZ).date() if entry.tzinfo else entry.date()
        path = massive.local_path("minute", day)
        if not path.exists():
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


def trade_figure(trade: pd.Series, bars: pd.DataFrame, title: str) -> go.Figure:
    """Candles with the entry/exit marked (blue win, red loss) and the stop, if any."""
    fig = go.Figure(
        go.Candlestick(
            x=bars.index,
            open=bars["open"],
            high=bars["high"],
            low=bars["low"],
            close=bars["close"],
            name=str(trade["symbol"]),
            increasing_line_color=NEUTRAL,
            decreasing_line_color="#52514e",
        )
    )
    color = WIN if trade["pnl"] > 0 else LOSS
    fig.add_scatter(
        x=[trade["entry_time"], trade["exit_time"]],
        y=[trade["entry_px"], trade["exit_px"]],
        mode="markers+lines+text",
        text=["entry", f"exit ({trade.get('exit_reason', '')})"],
        textposition="top center",
        name="trade",
        marker=dict(size=11, color=color, line=dict(width=2, color="white")),
        line=dict(color=color, width=2),
    )
    stop = trade.get("stop_px")
    if stop is not None and pd.notna(stop):
        fig.add_hline(
            y=stop, line=dict(color=LOSS, width=1), annotation_text="stop",
            annotation_position="right",
        )  # fmt: skip
    return style(fig, 460, title=title, xaxis_rangeslider_visible=False, hovermode="closest")
