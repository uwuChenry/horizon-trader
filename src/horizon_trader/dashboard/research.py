"""Research page: the markdown notes under research/ and every paper they cite.

Add a note by dropping a .md file into research/. Its first "# " heading becomes the title, and
any link in it (markdown or bare URL) shows up in the Papers tab.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from horizon_trader import config
from horizon_trader.dashboard import notes as N

root = config.REPO_ROOT / "research"
all_notes = N.list_notes(root)
st.sidebar.title("Research")
query = st.sidebar.text_input("Search", placeholder="e.g. PEAD, slippage, Lopez-Lira")
q = query.lower().strip()
shown = [p for p in all_notes if q in p.read_text(encoding="utf-8").lower()] if q else all_notes

st.title("Research")
if not all_notes:
    st.info("No research notes yet: add .md files to research/.")
    st.stop()

tab_notes, tab_papers = st.tabs(["Notes", "Papers"])

with tab_notes:
    if not shown:
        st.info(f"No research notes mention '{query}'.")
    else:
        pick = st.sidebar.radio("Note", shown, format_func=N.note_title)
        updated = datetime.fromtimestamp(pick.stat().st_mtime)
        st.caption(f"`research/{pick.name}` · updated {updated:%Y-%m-%d %H:%M}")
        st.markdown(pick.read_text(encoding="utf-8"))

with tab_papers:
    papers = N.papers(all_notes)
    if q:
        hit = papers[["title", "url", "cited in"]].apply(lambda c: c.str.lower().str.contains(q))
        papers = papers[hit.any(axis=1)]
    st.caption(
        f"{len(papers)} papers and sources cited across the notes. Click a link to open it. "
        "SSRN sometimes blocks direct links; search the title if one doesn't load."
    )
    st.dataframe(
        papers[["title", "url", "source", "cited in"]],
        column_config={
            "title": st.column_config.TextColumn("Paper / source", width="large"),
            "url": st.column_config.LinkColumn("Link", display_text="open ↗"),
            "source": st.column_config.TextColumn("Site"),
            "cited in": st.column_config.TextColumn("Cited in"),
        },
        hide_index=True,
        width="stretch",
        height=min(40 + 35 * len(papers), 800),
    )
