"""ORB day page: pick a day, see that day's Stocks in Play and each trade on a minute chart."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from horizon_trader.dashboard import orb_view as V

MODE = "path"


@st.cache_data(show_spinner="Loading the ORB trade table...")
def trades(name: str) -> pd.DataFrame:
    return V.load_trades(name)


@st.cache_data(show_spinner=False)
def bars(day, ticker: str) -> pd.DataFrame:
    return V.session_bars(day, ticker)


widths = V.stop_widths()
st.sidebar.title("ORB day")
if not widths:
    st.title("ORB day")
    st.info("No ORB trade table yet. Build it with `uv run python -m horizon_trader.intraday.orb`.")
    st.stop()

label = st.sidebar.selectbox(
    "Stop width", list(widths), index=0, help="1 ATR is our robustness setup; 0.1 ATR the paper's."
)
top_n = st.sidebar.select_slider("Stocks traded per day (top N)", [1, 2, 5, 10, 20], value=1)
t = trades(widths[label])
days = pd.DatetimeIndex(sorted(t["date"].unique()))

# jump buttons: the account's own trades (top N), gross R
taken = t[(t["rank"] <= top_n) & t["triggered"]]
r = taken["side"] * (taken[f"exit_px_{MODE}"] - taken["entry_px"]) / taken["stop_dist"]
by_day = r.groupby(taken["date"]).sum()
if "orb_day" not in st.session_state:
    st.session_state.orb_day = by_day.index[-1] if len(by_day) else days[-1]
c1, c2, c3, c4 = st.sidebar.columns(4)
if c1.button("Latest", width="stretch"):
    st.session_state.orb_day = by_day.index[-1]
if c2.button("Best", width="stretch"):
    st.session_state.orb_day = by_day.idxmax()
if c3.button("Worst", width="stretch"):
    st.session_state.orb_day = by_day.idxmin()
if c4.button("Random", width="stretch"):
    st.session_state.orb_day = by_day.index[np.random.default_rng().integers(len(by_day))]
day = pd.Timestamp(
    st.sidebar.date_input(
        "Day", value=st.session_state.orb_day, min_value=days[0], max_value=days[-1]
    )
)
if day not in days:
    day = days[days.searchsorted(day) - 1] if days.searchsorted(day) > 0 else days[0]
    st.sidebar.caption(f"No trading data that day; showing {day.date()}.")
st.session_state.orb_day = day
slip = st.sidebar.number_input(
    "Slippage per stop fill ($/share)",
    0.0,
    0.5,
    0.0,
    0.01,
    help="Measured on 1-second bars: ~0.045 for a stop-market entry.",
)

st.title(f"ORB day: {day:%A %d %b %Y}")
with st.expander("How the strategy works (rules)", expanded=False):
    st.markdown(V.RULES_MD)

table = V.day_table(t, day, top_n, MODE)
if table.empty:
    st.info("No stock passed the filters that day.")
    st.stop()

mine = table[table["taken"]]
cols = st.columns(4)
cols[0].metric("Stocks in play (candidates)", len(table))
cols[1].metric(f"Top {top_n} that broke out", f"{int(mine['triggered'].sum())} of {len(mine)}")
cols[2].metric("Day result (gross, R)", f"{mine['R'].fillna(0).sum():+.2f} R")

sized = []
for _, row in mine[mine["triggered"]].iterrows():
    p = V.trade_path(row, bars(day.date(), row["ticker"]), MODE)
    sized.append(V.size_trade(row, p, top_n, slippage=slip))
net = sum(s["net $"] for s in sized)
cols[3].metric("Day P&L on $5,000 (IBKR Tiered)", f"${net:+,.2f}")

show = table.head(max(10, top_n)).copy()
show["OR level"] = show["level"]
view = show[
    [
        "rank",
        "ticker",
        "taken",
        "relvol",
        "direction",
        "OR level",
        "stop_px",
        "triggered",
        "entry_time",
        "exit_reason",
        f"exit_px_{MODE}",
        "R",
    ]
]
st.subheader("Stocks in play, by relative volume")
st.dataframe(
    view.rename(
        columns={
            "stop_px": "stop",
            f"exit_px_{MODE}": "exit",
            "relvol": "rel. volume",
            "taken": "traded",
            "triggered": "broke out",
        }
    ),
    hide_index=True,
    width="stretch",
    column_config={
        "rel. volume": st.column_config.NumberColumn(format="%.1fx"),
        "OR level": st.column_config.NumberColumn(format="%.2f"),
        "stop": st.column_config.NumberColumn(format="%.2f"),
        "exit": st.column_config.NumberColumn(format="%.2f"),
        "R": st.column_config.NumberColumn(format="%+.2f"),
        "entry_time": st.column_config.DatetimeColumn("entry", format="HH:mm"),
    },
)

tickers = show["ticker"].tolist()
pick = st.selectbox(
    "Chart",
    tickers,
    index=0,
    format_func=lambda x: (
        f"#{int(show.set_index('ticker').at[x, 'rank'])} {x}"
        + ("" if show.set_index("ticker").at[x, "taken"] else "  (not traded at this top N)")
    ),
)
row = table.set_index("ticker").loc[pick].copy()
row["ticker"] = pick
b = bars(day.date(), pick)
path = V.trade_path(row, b, MODE)
title = (
    f"{pick}: #{int(row['rank'])} by relative volume ({row['relvol']:.1f}x), "
    f"{'long' if row['side'] > 0 else 'short'} setup"
)
st.plotly_chart(V.day_figure(b, row, path, title), width="stretch")

if not path["triggered"]:
    st.info(
        f"The price never broke the opening-range {'high' if row['side'] > 0 else 'low'} "
        f"({row['level']:.2f}), so there was no trade."
    )
else:
    s = V.size_trade(row, path, top_n, slippage=slip)
    r_mult = row["side"] * (path["exit_px"] - path["entry_px"]) / row["stop_dist"]
    st.markdown(
        f"**{'Bought' if row['side'] > 0 else 'Shorted'} {s['shares']:,.0f} shares at "
        f"{path['entry_px']:.2f}** ({path['entry_time']:%H:%M}), "
        f"${s['position $']:,.0f} of stock, risking ${s['risk $']:,.0f} (1% of $5,000) to a "
        f"stop at {path['stop_px']:.2f}. **Exit {path['exit_px']:.2f}** at "
        f"{path['exit_time']:%H:%M} by {path['exit_reason']}: {r_mult:+.2f} R, "
        f"${s['gross $']:+,.2f} gross, ${s['costs $']:.2f} IBKR Tiered costs, "
        f"**${s['net $']:+,.2f} net**."
    )
    if path["same_minute_stop"]:
        st.warning(
            "The stop was touched inside the entry minute. Minute bars can't say whether "
            "that happened before or after the fill; the chart uses the open-low-high-"
            "close guess. Treat this trade's result as uncertain."
        )
