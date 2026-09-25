"""Backtest dashboard: reads result bundles (data/results) and shows performance and trades.

    uv run python -m horizon_trader.dashboard

The dashboard only displays; every number comes from backtest/analytics.py (tested), so the
dashboard and the CLI reports can't disagree. Create bundles with --save on the backtests.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from horizon_trader.backtest import analytics as A
from horizon_trader.backtest import bundle
from horizon_trader.dashboard import charts as C
from horizon_trader.dashboard.charts import DIVERGING, LOSS, NEUTRAL, SERIES, WIN, style

PCT = {
    "total return",
    "CAGR",
    "vol",
    "max DD",
    "best day",
    "worst day",
    "% up days",
    "win rate",
    "costs / gross profit",
    "best 5% share of P&L",
    "% long",
    "alpha/yr",
}
MONEY = {
    "start equity",
    "end equity",
    "total P&L",
    "avg win",
    "avg loss",
    "expectancy $",
    "largest win",
    "largest loss",
    "gross P&L",
    "costs",
}

st.set_page_config(page_title="horizon-trader backtests", layout="wide")


# ---------------------------------------------------------------- data


@st.cache_data(show_spinner=False)
def load(run_id: str) -> bundle.Run:
    return bundle.load_run(run_id)


def fmt(key: str, v) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-" if v is None or np.isnan(v) else ("inf" if v > 0 else "-inf")
    if key in PCT:
        return f"{v:.1%}"
    if key in MONEY:
        return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"
    if isinstance(v, (int, np.integer)) or (
        isinstance(v, float) and v.is_integer() and abs(v) > 10
    ):
        return f"{v:,.0f}"
    return f"{v:,.2f}"


def stats_table(stats: dict) -> pd.DataFrame:
    return pd.DataFrame({"value": {k: fmt(k, v) for k, v in stats.items()}})


def naive_day(times: pd.Series) -> pd.Series:
    t = times.dt.tz_localize(None) if times.dt.tz is not None else times
    return t.dt.normalize()


def benchmark_equity(run: bundle.Run) -> pd.Series | None:
    """Benchmark rescaled to the strategy's starting equity (buy and hold)."""
    if run.benchmark is None or run.benchmark.dropna().empty:
        return None
    b = run.benchmark.reindex(run.equity.index).ffill().bfill()
    return b / b.iloc[0] * run.equity.iloc[0]


def add_dimensions(t: pd.DataFrame) -> pd.DataFrame:
    """Derived columns to slice trades by."""
    t = t.copy()
    t["side label"] = t["side"].map({1: "long", -1: "short"})
    t["result"] = np.where(t["pnl"] > 0, "win", "loss")
    entry = t["entry_time"]
    t["weekday"] = pd.Categorical(
        entry.dt.day_name().str[:3], ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ordered=True
    )
    t["year"] = entry.dt.year
    intraday = (t["exit_time"] - t["entry_time"]).max() < pd.Timedelta(days=1)
    if intraday:
        t["entry time"] = entry.dt.floor("30min").dt.strftime("%H:%M")
    top = t["symbol"].value_counts().head(12).index
    t["symbol (top 12)"] = t["symbol"].where(t["symbol"].isin(top), "other")
    if "relvol" in t:
        t["relative volume"] = pd.cut(t["relvol"], [1, 2, 3, 5, 10, 30, np.inf], right=False)
    held = (t["exit_time"] - t["entry_time"]) / pd.Timedelta(hours=1)
    edges = [0, 1, 3, 6.5, 24, 24 * 7, 24 * 30, np.inf] if not intraday else [0, 0.5, 1, 2, 4, 7]
    t["holding (h)"] = pd.cut(held, edges, right=False)
    return t


# ---------------------------------------------------------------- sidebar

runs = bundle.list_runs()
st.sidebar.title("Backtests")
if runs.empty:
    st.info(
        "No saved runs yet. Create some with `--save`, e.g.\n\n"
        "`uv run python -m horizon_trader.intraday.orb --stop-atr 1.0 --save`\n\n"
        "`uv run python -m horizon_trader.backtest.run --save`"
    )
    st.stop()

strategies = sorted(runs["strategy"].dropna().unique())
chosen = st.sidebar.multiselect("Strategy", strategies, default=strategies)
listed = runs[runs["strategy"].isin(chosen)] if chosen else runs
labels = {r.run_id: f"{r.name}  ·  {r.created[:16].replace('T', ' ')}" for r in listed.itertuples()}
run_id = st.sidebar.selectbox("Run", list(labels), format_func=lambda rid: labels.get(rid, rid))
run = load(run_id)
meta = run.meta
st.sidebar.caption(
    f"{meta.get('start')} → {meta.get('end')}  \ncommit `{meta.get('git_commit')}`"
    + (" (uncommitted changes)" if meta.get("git_dirty") else "")
)
oos = meta.get("oos_start")

trades = add_dimensions(run.trades) if len(run.trades) else run.trades
bench = benchmark_equity(run)
eq_stats = A.equity_stats(run.equity, run.benchmark)
tr_stats = A.trade_stats(run.trades)

# ---------------------------------------------------------------- header

st.title(meta.get("name", run_id))
st.caption(meta.get("strategy", ""))
kpis = [
    ("Total P&L", fmt("total P&L", eq_stats["total P&L"])),
    ("CAGR", fmt("CAGR", eq_stats["CAGR"])),
    ("Sharpe", fmt("Sharpe", eq_stats["Sharpe"])),
    ("Max drawdown", fmt("max DD", eq_stats["max DD"])),
    ("Profit factor", fmt("", tr_stats.get("profit factor", np.nan))),
    ("Win rate", fmt("win rate", tr_stats.get("win rate", np.nan))),
    ("Trades", f"{tr_stats.get('trades', 0):,}"),
    (
        "Expectancy",
        f"{tr_stats['expectancy R']:+.2f}R"
        if "expectancy R" in tr_stats
        else fmt("expectancy $", tr_stats.get("expectancy $", np.nan)),
    ),
]
for col, (label, value) in zip(st.columns(len(kpis)), kpis, strict=True):
    col.metric(label, value)
if meta.get("caveats"):
    st.caption("⚠ " + " · ".join(meta["caveats"][:2]) + "  (all caveats: Honesty tab)")

tabs = st.tabs(["Overview", "Performance", "Trades", "Costs", "Compare", "Honesty"])

# ---------------------------------------------------------------- overview

with tabs[0]:
    log = st.toggle("Log scale", value=eq_stats["total return"] > 1.0)
    fig = go.Figure()
    fig.add_scatter(
        x=run.equity.index, y=run.equity, name="strategy", line=dict(color=SERIES[0], width=2)
    )
    if bench is not None:
        fig.add_scatter(
            x=bench.index,
            y=bench,
            name=meta.get("benchmark", "benchmark"),
            line=dict(color=SERIES[1], width=2),
        )
    if oos:
        fig.add_vline(x=pd.Timestamp(oos), line=dict(color=NEUTRAL, width=1))
        fig.add_annotation(
            x=pd.Timestamp(oos),
            y=1,
            yref="paper",
            text="out-of-sample →",
            showarrow=False,
            xanchor="left",
            font=dict(color=NEUTRAL),
        )
    style(fig, 420, title="Equity", yaxis_type="log" if log else "linear", yaxis_tickprefix="$")
    st.plotly_chart(fig, width="stretch")

    dd = A.drawdown(run.equity)
    fig = go.Figure(
        go.Scatter(
            x=dd.index, y=dd, fill="tozeroy", name="drawdown", line=dict(color=LOSS, width=1.5)
        )
    )
    st.plotly_chart(
        style(fig, 220, title="Drawdown (underwater)", yaxis_tickformat=".0%", showlegend=False),
        width="stretch",
    )

    left, right = st.columns(2)
    left.subheader("Portfolio")
    left.dataframe(stats_table(eq_stats), width="stretch")
    right.subheader("Trades")
    right.dataframe(stats_table(tr_stats), width="stretch")

# ---------------------------------------------------------------- performance

with tabs[1]:
    m = A.monthly_returns(run.equity)
    months = [c for c in m.columns if c != "Year"]
    z = m[months].to_numpy() * 100
    lim = np.nanmax(np.abs(z)) if np.isfinite(z).any() else 1
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=months,
            y=m.index.astype(str),
            colorscale=DIVERGING,
            zmin=-lim,
            zmax=lim,
            zmid=0,
            xgap=2,
            ygap=2,
            text=np.where(np.isnan(z), "", np.char.mod("%.1f%%", z)),
            texttemplate="%{text}",
            hovertemplate="%{y} %{x}: %{z:.2f}%<extra></extra>",
            colorbar=dict(title="%"),
        )
    )
    st.plotly_chart(
        style(fig, 80 + 32 * len(m), title="Monthly returns", hovermode="closest"),
        width="stretch",
    )
    st.dataframe(m.map(lambda v: "" if pd.isna(v) else f"{v:.1%}"), width="stretch")

    c1, c2 = st.columns(2)
    window = c1.select_slider("Rolling window (trading days)", [63, 126, 252], value=126)
    rs = A.rolling_sharpe(run.equity, window)
    fig = go.Figure(
        go.Scatter(x=rs.index, y=rs, name="rolling Sharpe", line=dict(color=SERIES[0], width=2))
    )
    fig.add_hline(y=0, line=dict(color=NEUTRAL, width=1))
    c1.plotly_chart(
        style(fig, 300, title=f"Rolling Sharpe ({window}d)", showlegend=False),
        width="stretch",
    )
    r = A.returns(run.equity)
    fig = go.Figure()
    fig.add_histogram(x=r[r >= 0] * 100, name="up days", marker_color=WIN, xbins=dict(size=0.25))
    fig.add_histogram(x=r[r < 0] * 100, name="down days", marker_color=LOSS, xbins=dict(size=0.25))
    c2.plotly_chart(
        style(
            fig, 300, title="Daily returns (%)", barmode="overlay", bargap=0.05, hovermode="closest"
        ),
        width="stretch",
    )

    st.subheader("Worst drawdowns")
    dp = A.drawdown_periods(run.equity)
    if len(dp):
        show = dp.assign(depth=dp["depth"].map("{:.1%}".format))
        for c in ("start", "trough", "end"):
            show[c] = show[c].dt.date
        st.dataframe(show, width="stretch", hide_index=True)

# ---------------------------------------------------------------- trades

with tabs[2]:
    if trades.empty:
        st.info("This run has no trades.")
    else:
        has_r = "R" in trades
        unit = st.radio("P&L unit", ["$", "R"] if has_r else ["$"], horizontal=True)
        val = trades["R"] if unit == "R" else trades["pnl"]
        c1, c2 = st.columns(2)
        fig = go.Figure()
        fig.add_histogram(x=val[val > 0], name="wins", marker_color=WIN, nbinsx=60)
        fig.add_histogram(x=val[val <= 0], name="losses", marker_color=LOSS, nbinsx=60)
        c1.plotly_chart(
            style(
                fig,
                330,
                title=f"P&L per trade ({unit})",
                barmode="overlay",
                bargap=0.05,
                hovermode="closest",
            ),
            width="stretch",
        )

        cum = trades["pnl"].cumsum()
        fig = go.Figure(
            go.Scatter(
                x=np.arange(1, len(cum) + 1),
                y=cum,
                name="cumulative P&L",
                line=dict(color=SERIES[0], width=2),
            )
        )
        c2.plotly_chart(
            style(
                fig,
                330,
                title="Cumulative P&L by trade number",
                showlegend=False,
                yaxis_tickprefix="$",
                xaxis_title="trade #",
            ),
            width="stretch",
        )

        s = A.streaks(trades["pnl"])
        c1, c2 = st.columns(2)
        counts = s.groupby(["kind", "length"]).size().unstack(0, fill_value=0)
        fig = go.Figure()
        for kind, color in (("win", WIN), ("loss", LOSS)):
            if kind in counts:
                fig.add_bar(
                    x=counts.index, y=counts[kind], name=f"{kind} streaks", marker_color=color
                )
        c1.plotly_chart(
            style(
                fig,
                300,
                title="Streak lengths (consecutive wins / losses)",
                barmode="group",
                bargap=0.2,
                xaxis_title="length",
                hovermode="closest",
            ),
            width="stretch",
        )
        c2.metric("Longest win streak", tr_stats["max win streak"])
        c2.metric("Longest loss streak", tr_stats["max loss streak"])
        worst = s[s.kind == "loss"].sort_values("pnl").head(1)
        if len(worst):
            c2.metric(
                "Worst losing streak ($)",
                fmt("total P&L", worst["pnl"].iloc[0]),
                help="Sum of P&L over the costliest run of consecutive losses",
            )

        if {"mae_R", "mfe_R"} <= set(trades.columns):
            st.subheader("How far trades went against you, and in your favour")
            st.caption(
                "MAE = worst point before exit, MFE = best point, both in R at minute "
                "resolution. Given back = MFE minus the realised R."
            )
            c1, c2 = st.columns(2)
            fig = go.Figure()
            for res, color in (("win", WIN), ("loss", LOSS)):
                x = trades[trades["result"] == res]
                fig.add_scatter(
                    x=x["mae_R"],
                    y=x["mfe_R"],
                    mode="markers",
                    name=res + "s",
                    marker=dict(
                        color=color, size=8, opacity=0.6, line=dict(width=1, color="white")
                    ),
                )
            c1.plotly_chart(
                style(
                    fig,
                    360,
                    title="MAE vs MFE (R)",
                    xaxis_title="MAE (R)",
                    yaxis_title="MFE (R)",
                    hovermode="closest",
                ),
                width="stretch",
            )
            given = trades["mfe_R"] - trades["R"]
            fig = go.Figure(
                go.Histogram(x=given, marker_color=SERIES[0], nbinsx=60, name="given back")
            )
            c2.plotly_chart(
                style(
                    fig,
                    360,
                    title="Profit given back before exit (R)",
                    showlegend=False,
                    hovermode="closest",
                ),
                width="stretch",
            )

        st.subheader("Breakdown")
        dims = [
            d
            for d in (
                "exit_reason",
                "side label",
                "weekday",
                "entry time",
                "year",
                "holding (h)",
                "relative volume",
                "rank",
                "symbol (top 12)",
            )
            if d in trades.columns
        ]
        dim = st.selectbox("Slice trades by", dims)
        b = A.breakdown(trades, dim)
        c1, c2 = st.columns([3, 2])
        col = "avg R" if (unit == "R" and "avg R" in b) else "avg P&L"
        fig = go.Figure(
            go.Bar(
                x=b.index.astype(str),
                y=b[col],
                marker_color=np.where(b[col] >= 0, WIN, LOSS),
                customdata=b["trades"],
                hovertemplate="%{x}: %{y:.2f} (%{customdata} trades)<extra></extra>",
            )
        )
        c1.plotly_chart(
            style(
                fig, 320, title=f"{col} by {dim}", bargap=0.3, showlegend=False, hovermode="closest"
            ),
            width="stretch",
        )
        shown = b.copy()
        shown["win rate"] = shown["win rate"].map("{:.0%}".format)
        c2.dataframe(shown.round(2), width="stretch")

        st.subheader("Trade list")
        cols = [
            c
            for c in (
                "entry_time",
                "exit_time",
                "symbol",
                "side label",
                "qty",
                "entry_px",
                "exit_px",
                "pnl",
                "R",
                "exit_reason",
                "costs",
                "mae_R",
                "mfe_R",
                "relvol",
                "rank",
            )
            if c in trades.columns
        ]
        table = trades[cols].copy()
        numeric = table.select_dtypes("number").columns
        table[numeric] = table[numeric].round(3)
        pick = st.dataframe(
            table,
            width="stretch",
            height=320,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
        )
        rows = pick.selection.rows if pick is not None else []
        if rows:
            tr = trades.iloc[rows[0]]
            bars = C.trade_bars(tr, meta.get("chart"))
            if len(bars):
                day = naive_day(pd.Series([tr.entry_time])).iloc[0].date()
                title = (
                    f"{tr.symbol} {day}  ·  {tr['side label']}  ·  P&L {fmt('total P&L', tr.pnl)}"
                )
                st.plotly_chart(C.trade_figure(tr, bars, title), width="stretch")
            else:
                st.info("No local price data for this trade.")
        else:
            st.caption("Select a row to chart that trade.")

# ---------------------------------------------------------------- costs

with tabs[3]:
    if trades.empty:
        st.info("This run has no trades.")
    else:
        g = trades.sort_values("exit_time")
        fig = go.Figure()
        fig.add_scatter(
            x=g["exit_time"],
            y=g["gross"].cumsum(),
            name="before costs",
            line=dict(color=SERIES[0], width=2),
        )
        fig.add_scatter(
            x=g["exit_time"],
            y=g["pnl"].cumsum(),
            name="after costs",
            line=dict(color=SERIES[1], width=2),
        )
        st.plotly_chart(
            style(fig, 380, title="Cumulative P&L before vs after costs", yaxis_tickprefix="$"),
            width="stretch",
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Total costs", fmt("costs", tr_stats["costs"]))
        c2.metric(
            "Costs / gross profit", fmt("costs / gross profit", tr_stats["costs / gross profit"])
        )
        c3.metric("Avg cost per trade", f"${trades['costs'].mean():,.2f}")
        by_year = g.groupby(g["exit_time"].dt.year)[["gross", "costs", "pnl"]].sum()
        by_year.index.name = "year"
        st.dataframe(by_year.round(0), width="stretch")
        st.caption(
            "Costs are commissions and regulatory fees. Slippage is already inside the fill "
            "prices, so it shows up in 'before costs' P&L rather than here."
        )

# ---------------------------------------------------------------- compare

with tabs[4]:
    options = list(labels)
    picked = st.multiselect(
        "Runs to compare (up to 4)",
        options,
        default=[run_id],
        format_func=lambda rid: labels.get(rid, rid),
        max_selections=4,
    )
    if picked:
        fig, rows = go.Figure(), {}
        for i, rid in enumerate(picked):
            r = load(rid)
            norm = r.equity / r.equity.iloc[0]
            name = r.meta.get("name", rid)
            fig.add_scatter(x=norm.index, y=norm, name=name, line=dict(color=SERIES[i], width=2))
            rows[name] = {
                k: fmt(k, v)
                for k, v in (A.equity_stats(r.equity) | A.trade_stats(r.trades)).items()
            }
        st.plotly_chart(style(fig, 420, title="Growth of $1", yaxis_type="log"), width="stretch")
        st.dataframe(pd.DataFrame(rows), width="stretch")
        st.caption("Different runs can cover different date ranges; compare over matching periods.")

# ---------------------------------------------------------------- honesty

with tabs[5]:
    st.subheader("Caveats")
    for c in meta.get("caveats", []) or ["None recorded for this run."]:
        st.markdown(f"- {c}")
    if oos and len(run.trades):
        st.subheader(f"In-sample vs out-of-sample (split {oos})")
        st.caption(
            "If the second column is much worse than the first, the result is probably "
            "fitted to the past."
        )
        split = A.split_stats(run.equity, run.trades, oos)
        keys = [
            "CAGR",
            "Sharpe",
            "max DD",
            "trades",
            "win rate",
            "profit factor",
            "expectancy $",
            "expectancy R",
            "costs / gross profit",
        ]
        split = split.reindex([k for k in keys if k in split.index])
        st.dataframe(split.apply(lambda col: [fmt(k, v) for k, v in col.items()]), width="stretch")
    if "best 5% share of P&L" in tr_stats:
        share = tr_stats["best 5% share of P&L"]
        st.metric(
            "Share of P&L from the best 5% of trades",
            f"{share:.0%}",
            help="Above 100% means the other 95% of trades lost money in total.",
        )
    st.subheader("Run details")
    st.markdown(
        f"Code: commit `{meta.get('git_commit')}`"
        + (" **with uncommitted changes**" if meta.get("git_dirty") else "")
    )
    st.code(json.dumps(meta.get("params", {}), indent=2, default=str), language="json")
