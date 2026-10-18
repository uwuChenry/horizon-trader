"""Shared viewers for typed artifacts in old and new result formats."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from horizon_trader.results.catalog import Artifact, equity_curves, read_table


def render_artifact(artifact: Artifact, key: str) -> None:
    path = artifact.path
    if not path.is_file():
        st.warning(f"Artifact unavailable locally: {artifact.label}")
        return
    stamp = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC")
    st.caption(f"{artifact.label} · saved {stamp:%Y-%m-%d %H:%M} UTC")
    try:
        if path.suffix in {".csv", ".parquet", ".jsonl"}:
            frame = read_table(path)
            if artifact.role == "equity" and not frame.empty:
                curves = equity_curves(frame)
                if not curves.empty:
                    st.caption(
                        f"Data: {curves.index.min():%Y-%m-%d} to {curves.index.max():%Y-%m-%d}"
                    )
                    chosen = st.multiselect(
                        "Series", list(curves), default=list(curves)[:4], key=f"{key}:series"
                    )
                    if chosen:
                        shown = curves[chosen]
                        if st.checkbox("Growth of $1", key=f"{key}:normalize"):
                            shown = shown.div(
                                shown.apply(
                                    lambda col: (
                                        col.dropna().iloc[0] if col.notna().any() else float("nan")
                                    )
                                )
                            )
                        st.line_chart(shown)
            # Filters expose all grid configurations without silently selecting a winner.
            dimensions = [
                c
                for c in [
                    "period",
                    "strategy",
                    "variant",
                    "capital",
                    "scenario",
                    "exit_rule",
                    "stop_atr",
                    "risk_budget",
                    "leverage_cap",
                    "cost_case",
                    "restart",
                    "kind",
                ]
                if c in frame and 1 < frame[c].nunique() <= 100
            ]
            if dimensions:
                with st.expander("Filter rows"):
                    for column in dimensions:
                        values = frame[column].dropna().unique().tolist()
                        selected = st.multiselect(column, values, key=f"{key}:filter:{column}")
                        if selected:
                            frame = frame[frame[column].isin(selected)]
            st.caption(
                f"{len(frame):,} rows · preview shows up to 2,000; download contains all rows"
            )
            st.dataframe(frame.head(2000), width="stretch")
        elif path.suffix == ".json":
            st.json(json.loads(path.read_text(encoding="utf-8")), expanded=False)
        elif path.suffix == ".md":
            st.markdown(path.read_text(encoding="utf-8"))
        elif path.suffix == ".html":
            # Standalone Plotly artifacts retain their interactions when opened locally.
            st.info("Download this interactive chart and open it in your browser.")
        else:
            st.code(path.read_text(encoding="utf-8"), language=None)
        st.download_button(
            "Download original file", path.read_bytes(), file_name=path.name, key=f"{key}:download"
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"Could not display {path.name}: {exc}")
