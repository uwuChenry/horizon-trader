"""ORB day viewer logic: one day's Stocks in Play, each trade's path, and a TradingView-style
chart. Reads the cached trade tables from `intraday.orb` (build them with
`uv run python -m horizon_trader.intraday.orb`) and the Massive minute bars; nothing here
re-runs the strategy, so the page shows exactly what the backtest simulated."""

from __future__ import annotations

import re
from datetime import date

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from horizon_trader.datasources import massive
from horizon_trader.intraday import features as F
from horizon_trader.intraday import orb

UP, DOWN = "#26a69a", "#ef5350"  # TradingView's default candle colours
OR_FILL, LEVEL, STOP, ENTRY = "rgba(42,120,214,0.12)", "#2a78d6", "#e34948", "#2a78d6"
MINUTES = 5
CAPITAL = 5_000.0


def stop_widths() -> dict[str, str]:
    """{label: cache name} for every cached 5-minute trade table (no dollar-volume filter)."""
    out = {}
    for p in sorted(orb._derived_path("x").parent.glob(f"orb{MINUTES}_stop*_trades.parquet")):
        m = re.fullmatch(rf"orb{MINUTES}_stop([0-9.]+)_trades", p.stem)
        if m:
            out[f"{float(m.group(1)):g} ATR"] = p.stem
    return dict(sorted(out.items(), key=lambda kv: -float(kv[0].split()[0])))  # widest first


def load_trades(name: str) -> pd.DataFrame:
    t = orb._derived(name)
    return t.assign(date=pd.to_datetime(t["date"])) if t is not None else pd.DataFrame()


def day_table(
    trades: pd.DataFrame, day: pd.Timestamp, top_n: int, mode: str = "path"
) -> pd.DataFrame:
    """The day's candidates by relative-volume rank, with what happened to each. `taken` marks
    the ones the account trades (rank <= top_n); the rest are shown for context."""
    d = trades[trades["date"] == day].sort_values("rank")
    r = d["side"] * (d[f"exit_px_{mode}"] - d["entry_px"]) / d["stop_dist"]
    return d.assign(
        taken=d["rank"] <= top_n,
        direction=np.where(d["side"] > 0, "long", "short"),
        exit_reason=np.where(
            ~d["triggered"],
            "no breakout",
            np.where(d[f"stopped_{mode}"].fillna(False), "stop", "close"),
        ),
        R=r.where(d["triggered"]),
    )


def session_bars(day: date, ticker: str) -> pd.DataFrame:
    """That ticker's regular-session minute bars (9:30-16:00, bar-start times)."""
    start = F.session_open(day)
    window = [("ticker", "in", [ticker]), ("ts", ">=", start), ("ts", "<", start + orb.CLOSE_TIME)]
    return pd.read_parquet(massive.local_path("minute", day), filters=window).reset_index(drop=True)


def trade_path(row: pd.Series, bars: pd.DataFrame, mode: str = "path") -> dict:
    """Entry, stop and exit of one simulated trade, mapped back to clock times. The simulator
    indexes the bars after the opening range; an index past the last bar is the close."""
    start = F.session_open(row["date"].date())
    post = bars[bars["ts"] >= start + pd.Timedelta(minutes=MINUTES)].reset_index(drop=True)
    first = bars[bars["ts"] < start + pd.Timedelta(minutes=MINUTES)]
    out = {
        "or_high": first["high"].max(),
        "or_low": first["low"].min(),
        "level": row["level"],
        "triggered": bool(row["triggered"]),
    }
    if not row["triggered"]:
        return out
    k, j = int(row["entry_idx"]), int(row[f"exit_idx_{mode}"])
    stopped = bool(row[f"stopped_{mode}"])
    return out | {
        "entry_time": post["ts"].iloc[k],
        "entry_px": row["entry_px"],
        "stop_px": row["entry_px"] - row["side"] * row["stop_dist"],
        "exit_time": post["ts"].iloc[j] if j < len(post) else start + orb.CLOSE_TIME,
        "exit_px": row[f"exit_px_{mode}"],
        "exit_reason": "stop" if stopped else "close (market-on-close)",
        "same_minute_stop": bool(row["stopped_cons"]) and int(row["exit_idx_cons"]) == k,
    }


def size_trade(
    row: pd.Series,
    path: dict,
    top_n: int,
    equity: float = CAPITAL,
    plan: str = "tiered",
    slippage: float = 0.0,
) -> dict:
    """Shares and P&L as run_portfolio sizes them: risk 1% of equity at the stop, capped at 4x
    leverage split across the top N; IBKR costs; `slippage` $/share on each stop fill."""
    acct = orb.Account(equity=equity, top_n=top_n)
    side = int(row["side"])
    entry = path["entry_px"] + side * slippage
    stopped = path["exit_reason"] == "stop"
    exit_ = path["exit_px"] - side * slippage * stopped
    cap = acct.leverage * equity / top_n / entry
    qty = float(np.floor(min(acct.risk * equity / row["stop_dist"], cap)))
    gross = side * qty * (exit_ - entry)
    costs = float(orb.trade_costs([qty], [entry], [exit_], [side], plan, [not stopped])[0])
    return {
        "shares": qty,
        "position $": qty * entry,
        "gross $": gross,
        "costs $": costs,
        "net $": gross - costs,
        "risk $": qty * row["stop_dist"],
    }


def day_figure(bars: pd.DataFrame, row: pd.Series, path: dict, title: str) -> go.Figure:
    """Candles + volume, the opening-range box, the breakout level, and the trade: entry
    marker, stop line while the position is open, exit marker."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22], vertical_spacing=0.02
    )
    fig.add_candlestick(
        x=bars["ts"],
        open=bars["open"],
        high=bars["high"],
        low=bars["low"],
        close=bars["close"],
        name=str(row["ticker"]),
        increasing=dict(line=dict(color=UP), fillcolor=UP),
        decreasing=dict(line=dict(color=DOWN), fillcolor=DOWN),
        row=1,
        col=1,
    )
    colors = np.where(bars["close"] >= bars["open"], UP, DOWN)
    fig.add_bar(
        x=bars["ts"],
        y=bars["volume"],
        marker_color=colors,
        opacity=0.6,
        name="volume",
        row=2,
        col=1,
    )
    start = F.session_open(row["date"].date())
    or_end, close = start + pd.Timedelta(minutes=MINUTES), start + orb.CLOSE_TIME
    fig.add_shape(
        type="rect",
        x0=start,
        x1=or_end,
        y0=path["or_low"],
        y1=path["or_high"],
        fillcolor=OR_FILL,
        line=dict(color=LEVEL, width=1),
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=start,
        y=path["or_high"],
        text=f"{MINUTES}-min opening range",
        showarrow=False,
        yanchor="bottom",
        xanchor="left",
        font=dict(size=11),
        row=1,
        col=1,
    )
    side = int(row["side"])
    fig.add_scatter(
        x=[or_end, close],
        y=[path["level"]] * 2,
        mode="lines",
        line=dict(color=LEVEL, width=1, dash="dot"),
        name=f"breakout level ({'high' if side > 0 else 'low'} of the range)",
        row=1,
        col=1,
    )
    if path["triggered"]:
        t0, t1 = path["entry_time"], path["exit_time"]
        fig.add_scatter(
            x=[t0, t1],
            y=[path["stop_px"]] * 2,
            mode="lines",
            line=dict(color=STOP, width=1.5, dash="dash"),
            name=f"stop {path['stop_px']:.2f}",
            row=1,
            col=1,
        )
        fig.add_vrect(x0=t0, x1=t1, fillcolor="rgba(137,135,129,0.08)", line_width=0, row=1, col=1)
        verb_in, verb_out = ("BUY", "SELL") if side > 0 else ("SHORT", "COVER")
        win = side * (path["exit_px"] - path["entry_px"]) > 0
        fig.add_scatter(
            x=[t0],
            y=[path["entry_px"]],
            mode="markers+text",
            marker=dict(
                symbol="triangle-up" if side > 0 else "triangle-down",
                size=15,
                color=ENTRY,
                line=dict(color="white", width=1),
            ),
            text=[f"{verb_in} {path['entry_px']:.2f}"],
            textposition="bottom right",
            name=f"entry {t0:%H:%M}",
            row=1,
            col=1,
        )
        fig.add_scatter(
            x=[t1],
            y=[path["exit_px"]],
            mode="markers+text",
            marker=dict(
                symbol="x", size=13, color=UP if win else DOWN, line=dict(color="white", width=1)
            ),
            text=[f"{verb_out} {path['exit_px']:.2f} ({path['exit_reason'].split()[0]})"],
            textposition="top left",
            name=f"exit {t1:%H:%M}",
            row=1,
            col=1,
        )
    fig.update_layout(
        title=dict(text=title, y=0.985, yanchor="top"),
        height=640,
        margin=dict(l=10, r=10, t=90, b=10),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        bargap=0,
        legend=dict(orientation="h", y=1.01, yanchor="bottom", x=0),
    )
    spikes = dict(
        showspikes=True,
        spikemode="across",
        spikesnap="cursor",
        spikethickness=1,
        spikedash="dot",
        spikecolor="#898781",
    )
    fig.update_xaxes(showgrid=False, **spikes)
    fig.update_yaxes(gridcolor="rgba(137,135,129,0.2)", side="right", **spikes)
    fig.update_yaxes(title_text="volume", row=2, col=1, showspikes=False)
    return fig


RULES_MD = """**Opening Range Breakout on Stocks in Play** (Zarattini, Barbon & Aziz 2024,
[SSRN 4729284](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)). Every trading day:

1. **Universe:** every US common stock (delisted ones included) with an open above \\$5, a
   14-day average volume of at least 1M shares and a 14-day ATR above \\$0.50.
2. **Stocks in Play:** rank them by **relative volume**: shares traded in the first 5 minutes
   (9:30-9:35) vs the average first 5 minutes of the last 14 days. The account trades the
   **top N** (the paper: 20; our best realistic setup: 1).
3. **Direction:** if the 9:30-9:35 candle closed **up**, go long; **down**, go short; flat, skip.
4. **Entry:** a stop order at the **opening-range high** (long) or **low** (short). If the
   price never breaks it, no trade.
5. **Stop loss:** a fixed distance from the fill: 10% of ATR in the paper, **1 ATR** in our
   robustness tests (wider stops fix the minute-bar ambiguity and cut drawdowns).
6. **Exit:** at the stop, or else at the **4:00pm close** (market-on-close). No profit target,
   no trailing stop: those were tested and hurt (they cut off the big winners that carry the
   strategy).
7. **Size:** risk 1% of equity if stopped (shares = 1% of equity / stop distance), capped at
   4x intraday leverage split across the top N.

**What the chart can't show:** these are minute bars, so the simulated fill is the breakout
level (or the bar's open if it gapped through), with no slippage. Measured on 1-second bars,
a stop-market entry pays about **4.5 cents a share**; a stop-limit at the trigger avoids most
of that but misses the 3% of breakouts that run away. After costs and slippage the best setup
(top 1, 1 ATR stop, stop-limit) made about 12% a year at \\$5k with a -22% drawdown; see
`research/orb_*.md` before trusting any single day."""
