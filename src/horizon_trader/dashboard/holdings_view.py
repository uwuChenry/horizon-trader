"""Data shaping and figures for the Holdings page (kept out of the page script so they're testable).

Input tables come from result bundles (`bundle.Run.tables`):
    holdings  one row per (date, ticker) held: shares, price, value, weight (of equity)
    picks     optional; each formation's ranking: formation, rank, ticker, name, momentum,
              market_cap, selected
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from horizon_trader.dashboard.charts import GRID, NEUTRAL, SERIES, style

HELD, OTHER = SERIES[0], "rgba(137,135,129,0.45)"


def snap(calendar: pd.DatetimeIndex, t) -> pd.Timestamp:
    """The last trading day on or before t (the first one if t is earlier)."""
    i = calendar.searchsorted(pd.Timestamp(t), side="right") - 1
    return calendar[max(i, 0)]


def held_matrix(holdings: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """date x ticker booleans: held at that close."""
    h = holdings.assign(held=True).pivot_table(
        index="date", columns="ticker", values="held", aggfunc="any"
    )
    return h.reindex(calendar).fillna(False).astype(bool)


def entry_dates(held: pd.DataFrame) -> pd.DataFrame:
    """date x ticker: the first day of the current continuous holding (NaT when not held)."""
    starts = held & ~held.shift(fill_value=False)
    days = pd.DataFrame({c: held.index for c in held.columns}, index=held.index)
    return days.where(starts).ffill().where(held)


def holding_periods(held: pd.DataFrame) -> pd.DataFrame:
    """One row per continuous holding: ticker, start, end (last day held)."""
    rows = []
    idx = held.index
    for t in held.columns:
        h = held[t].to_numpy()
        i = 0
        while i < len(h):
            if h[i]:
                j = i
                while j + 1 < len(h) and h[j + 1]:
                    j += 1
                rows.append({"ticker": t, "start": idx[i], "end": idx[j]})
                i = j + 1
            else:
                i += 1
    return pd.DataFrame(rows, columns=["ticker", "start", "end"])


def formation_for(picks: pd.DataFrame, t: pd.Timestamp) -> pd.Timestamp | None:
    """The formation whose portfolio is held at the close of t: formed at a month-end close and
    traded at the next open, so the formation must be strictly before t."""
    f = picks.loc[picks["formation"] < t, "formation"]
    return f.max() if len(f) else None


def rebalance_changes(picks: pd.DataFrame, f: pd.Timestamp) -> dict[str, list[str]]:
    """Bought / sold / kept at formation f vs the previous formation."""
    sel = picks[picks["selected"]]
    now = set(sel.loc[sel["formation"] == f, "ticker"])
    prev_f = sel.loc[sel["formation"] < f, "formation"]
    before = set(sel.loc[sel["formation"] == prev_f.max(), "ticker"]) if len(prev_f) else set()
    return {
        "bought": sorted(now - before),
        "sold": sorted(before - now),
        "kept": sorted(now & before),
    }


def positions_at(
    holdings: pd.DataFrame,
    equity: pd.Series,
    t: pd.Timestamp,
    picks: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """The portfolio at the close of t, biggest first, with entry date, the move since then
    and (if picks are given) the name, rank and momentum at the formation being held."""
    cal = equity.index
    held = held_matrix(holdings, cal)
    entry = entry_dates(held)
    pos = holdings[holdings["date"] == t].set_index("ticker")
    if pos.empty:
        return pd.DataFrame(
            columns=["name", "weight", "value", "shares", "price", "held since",
                     "trading days held", "move since bought", "rank", "momentum"]
        )  # fmt: skip
    px_wide = holdings.pivot_table(index="date", columns="ticker", values="price")
    out = pd.DataFrame(index=pos.index)
    out["weight"] = pos["weight"]
    out["value"] = pos["value"]
    out["shares"] = pos["shares"]
    out["price"] = pos["price"]
    since = entry.loc[t, pos.index]
    out["held since"] = since
    pos_of = {d: i for i, d in enumerate(cal)}
    out["trading days held"] = [pos_of[t] - pos_of[d] + 1 for d in since]
    out["move since bought"] = [
        pos.at[k, "price"] / px_wide.at[d, k] - 1 for k, d in since.items()
    ]  # close on the day bought -> close at t
    out["name"], out["rank"], out["momentum"] = None, pd.NA, float("nan")
    if picks is not None and len(picks):
        names = picks.dropna(subset=["name"]).drop_duplicates("ticker", keep="last")
        out["name"] = names.set_index("ticker")["name"].reindex(out.index)
        f = formation_for(picks, t)
        if f is not None:
            ranked = picks[picks["formation"] == f].set_index("ticker")
            out["rank"] = ranked["rank"].reindex(out.index)
            out["momentum"] = ranked["momentum"].reindex(out.index)
    cols = ["name", "weight", "value", "shares", "price", "held since", "trading days held",
            "move since bought", "rank", "momentum"]  # fmt: skip
    return out[cols].sort_values("weight", ascending=False)


# ---------------------------------------------------------------- figures


def weights_figure(pos: pd.DataFrame, cash_weight: float) -> go.Figure:
    """Horizontal bars of % of equity per holding, plus cash (gray), biggest at the top."""
    labels = list(pos.index) + ["cash"]
    values = list(pos["weight"]) + [cash_weight]
    colors = [HELD] * len(pos) + [NEUTRAL]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color=colors, cornerradius=4),
            text=[f"{v:.1%}" for v in values],
            textposition="outside",
            hovertemplate="%{y}: %{x:.1%} of equity<extra></extra>",
        )
    )
    fig.update_yaxes(autorange="reversed")
    top = max([abs(v) for v in values] + [0.01])
    fig.update_xaxes(
        tickformat=".0%",
        showgrid=True,
        gridcolor=GRID,
        range=[min(0.0, min(values) * 1.2), top * 1.2],
    )  # room for labels
    return style(
        fig, max(260, 28 * len(labels) + 60), title="% of equity", hovermode="closest",
        showlegend=False, bargap=0.25,
    )  # fmt: skip


def equity_figure(equity: pd.Series, benchmark: pd.Series | None, t: pd.Timestamp) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=equity.index, y=equity, name="strategy", line=dict(color=SERIES[0], width=2))
    if benchmark is not None:
        b = benchmark.reindex(equity.index).ffill().dropna()
        if len(b):
            fig.add_scatter(
                x=b.index, y=b / b.iloc[0] * equity.iloc[0], name="SPY, same start",
                line=dict(color=SERIES[1], width=2),
            )  # fmt: skip
    fig.add_vline(x=t, line=dict(color=NEUTRAL, width=1, dash="dot"))
    fig.add_scatter(
        x=[t], y=[equity.loc[t]], mode="markers", name="selected day",
        marker=dict(size=10, color=SERIES[0], line=dict(width=2, color="white")),
        hovertemplate="%{x|%Y-%m-%d}: $%{y:,.0f}<extra></extra>",
    )  # fmt: skip
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return style(fig, 320, title="Equity ($5k start)")


def timeline_figure(periods: pd.DataFrame, t: pd.Timestamp) -> go.Figure:
    """Every holding period as a bar; periods covering t are highlighted."""
    p = periods.copy()
    p["state"] = ["held on selected day" if s <= t <= e else "other periods"
                  for s, e in zip(p["start"], p["end"], strict=True)]  # fmt: skip
    p["end_plot"] = p["end"] + pd.Timedelta(days=1)  # a one-day holding still shows
    order = p.groupby("ticker")["start"].min().sort_values().index.tolist()
    fig = px.timeline(
        p, x_start="start", x_end="end_plot", y="ticker", color="state",
        color_discrete_map={"held on selected day": HELD, "other periods": OTHER},
        category_orders={"ticker": order, "state": ["held on selected day", "other periods"]},
        hover_data={"start": "|%Y-%m-%d", "end": "|%Y-%m-%d", "end_plot": False, "state": False},
    )  # fmt: skip
    fig.add_vline(x=t, line=dict(color=NEUTRAL, width=1, dash="dot"))
    fig.update_yaxes(title=None, tickfont=dict(size=10))
    return style(
        fig, max(300, 14 * len(order) + 90), title="Every holding period (first bought, top)",
        hovermode="closest", margin=dict(l=10, r=10, t=80, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, title=None),
    )  # fmt: skip
