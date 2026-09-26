"""Holdings page: what a portfolio strategy held on any day, with a date slider.

Works for any result bundle with a "holdings" table (and, optionally, a "picks" ranking table),
e.g. `uv run python -m horizon_trader.backtest.winners --save`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from horizon_trader.backtest import bundle
from horizon_trader.dashboard import holdings_view as H

KEY = "holdings_day"


@st.cache_data(show_spinner=False)
def load(run_id: str) -> bundle.Run:
    return bundle.load_run(run_id)


@st.cache_data(show_spinner=False)
def periods(run_id: str) -> pd.DataFrame:
    r = load(run_id)
    return H.holding_periods(H.held_matrix(r.tables["holdings"], r.equity.index))


runs = bundle.list_runs()
runs = runs[[bundle.has_table(r, "holdings") for r in runs["run_id"]]] if len(runs) else runs
runs = runs.sort_values(["name", "created"], ascending=[True, False]) if len(runs) else runs
st.sidebar.title("Holdings")
if runs.empty:
    st.title("Holdings")
    st.info(
        "No runs with holdings yet. Create them with "
        "`uv run python -m horizon_trader.backtest.winners --save`."
    )
    st.stop()

run_id = st.sidebar.selectbox(
    "Run", runs["run_id"].tolist(),
    format_func=lambda r: str(runs.set_index("run_id").at[r, "name"]),
)  # fmt: skip
run = load(run_id)
holdings = run.tables["holdings"].assign(date=lambda d: pd.to_datetime(d["date"]))
picks = run.tables.get("picks")
if picks is not None:
    picks = picks.assign(formation=pd.to_datetime(picks["formation"]))
equity = run.equity
cal = equity.index

st.title(run.meta.get("name", run_id))
st.caption(
    f"{run.meta.get('strategy', '')} · {cal[0].date()} to {cal[-1].date()} · "
    f"{holdings['ticker'].nunique()} different stocks held"
)
if run.meta.get("how_it_works"):
    with st.expander("How this strategy works", expanded=False):
        st.markdown(run.meta["how_it_works"])
        for c in run.meta.get("caveats", []):
            st.caption(f"Caveat: {c}")

# ---------------------------------------------------------------- the day picker

if KEY not in st.session_state or st.session_state.get("holdings_run") != run_id:
    st.session_state[KEY] = cal[-1].date()
    st.session_state["holdings_run"] = run_id
rebalances = sorted(picks["formation"].unique()) if picks is not None else []


def _jump(step: int) -> None:
    """Move to the first trading day after the previous/next month-end formation."""
    t = H.snap(cal, st.session_state[KEY])
    trade_days = [cal[cal > f][0] for f in rebalances if (cal > f).any()]
    target = [d for d in trade_days if d < t] if step < 0 else [d for d in trade_days if d > t]
    if target:
        st.session_state[KEY] = (target[-1] if step < 0 else target[0]).date()


c1, c2, c3 = st.columns([1, 8, 1], vertical_alignment="bottom")
c1.button("◀ rebalance", on_click=_jump, args=(-1,), disabled=not rebalances,
          help="Previous month-end rebalance")  # fmt: skip
c2.slider(
    "Day", min_value=cal[0].date(), max_value=cal[-1].date(), key=KEY, format="YYYY-MM-DD",
    help="Positions at that day's close. Non-trading days snap to the previous trading day.",
)  # fmt: skip
c3.button("rebalance ▶", on_click=_jump, args=(1,), disabled=not rebalances,
          help="Next month-end rebalance")  # fmt: skip
t = H.snap(cal, st.session_state[KEY])

# ---------------------------------------------------------------- snapshot

pos = H.positions_at(holdings, equity, t, picks)
eq_t = float(equity.loc[t])
cash_w = 1.0 - float(pos["weight"].sum()) if len(pos) else 1.0
dd_t = eq_t / float(equity.loc[:t].max()) - 1
m = st.columns(5)
m[0].metric("Day", str(t.date()))
m[1].metric("Equity", f"${eq_t:,.0f}", f"{eq_t / equity.iloc[0] - 1:+.1%} since start")
m[2].metric("Below the high so far", f"{dd_t:.1%}")
m[3].metric("Positions", len(pos))
m[4].metric(
    "Cash",
    f"{cash_w:.1%}",
    help="Negative = borrowed. The simulator lets cash go slightly negative (a few % of equity) "
    "when positions inside the 2% rebalance band stay overweight while new ones are bought, "
    "and it charges no margin interest for it.",
)

left, right = st.columns([2, 3])
with left:
    st.plotly_chart(H.weights_figure(pos, cash_w), width="stretch")
with right:
    st.markdown("**Positions at the close**")
    st.dataframe(
        pos,
        width="stretch",
        column_config={
            "weight": st.column_config.NumberColumn("% of equity", format="percent"),
            "value": st.column_config.NumberColumn("value", format="dollar"),
            "shares": st.column_config.NumberColumn(format="%.4f"),
            "price": st.column_config.NumberColumn(format="dollar"),
            "held since": st.column_config.DateColumn(format="YYYY-MM-DD"),
            "move since bought": st.column_config.NumberColumn(
                format="percent", help="Close on the first day held to the close on this day."
            ),
            "rank": st.column_config.NumberColumn(help="Rank at the formation being held."),
            "momentum": st.column_config.NumberColumn(
                format="percent", help="The signal value at the formation being held."
            ),
        },
    )  # fmt: skip
    st.caption(
        "Prices are split-adjusted and exclude dividends. Weights drift daily; the backtest "
        "trades a position back to its target once it's more than 2 points away."
    )

# ---------------------------------------------------------------- the ranking behind it

if picks is not None:
    f = H.formation_for(picks, t)
    if f is None:
        st.info("Before the first formation: the portfolio is in cash.")
    else:
        traded = cal[cal > f]
        on = traded[0].date() if len(traded) else "-"
        st.subheader(f"Ranking at the {f.date()} close (traded at the {on} open)")
        ch = H.rebalance_changes(picks, f)
        b1, b2, b3 = st.columns(3)
        b1.markdown("**Bought:** " + (", ".join(ch["bought"]) or "nothing new"))
        b2.markdown("**Sold:** " + (", ".join(ch["sold"]) or "nothing"))
        b3.markdown("**Kept:** " + (", ".join(ch["kept"]) or "-"))
        ranked = picks[picks["formation"] == f].drop(columns="formation").set_index("rank")
        st.dataframe(
            ranked,
            width="stretch",
            column_config={
                "momentum": st.column_config.NumberColumn(format="percent"),
                "market_cap": st.column_config.NumberColumn("market cap", format="compact"),
                "selected": st.column_config.CheckboxColumn("bought"),
            },
        )  # fmt: skip

# ---------------------------------------------------------------- over time

st.plotly_chart(H.equity_figure(equity, run.benchmark, t), width="stretch")
st.plotly_chart(H.timeline_figure(periods(run_id), t), width="stretch")
