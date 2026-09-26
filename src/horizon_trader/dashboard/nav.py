"""Dashboard entry point: the backtest browser, strategy holdings and the research notes."""

from pathlib import Path

import streamlit as st

HERE = Path(__file__).resolve().parent  # absolute, however streamlit was launched

st.set_page_config(page_title="horizon-trader", layout="wide")
st.navigation(
    [
        st.Page(HERE / "app.py", title="Backtests", icon=":material/monitoring:", default=True),
        st.Page(HERE / "holdings.py", title="Holdings", icon=":material/pie_chart:"),
        st.Page(HERE / "research.py", title="Research", icon=":material/menu_book:"),
    ]
).run()
