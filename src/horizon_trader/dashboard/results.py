"""Unified dashboard landing page: results, evidence and latest test runs."""

from pathlib import Path

import pandas as pd
import streamlit as st

from horizon_trader import config
from horizon_trader.dashboard import notes
from horizon_trader.dashboard.artifacts import render_artifact
from horizon_trader.results.catalog import code_fingerprint, discover

st.title("Results")
st.caption("Saved backtests, research experiments, forward ledgers and verification results.")
st.sidebar.title("Results")
st.sidebar.button("Refresh results", help="Read the latest files from disk.")
records, issues = discover()
if issues:
    with st.expander(f"{len(issues)} catalog issues", expanded=True):
        for issue in issues:
            st.warning(issue)
if not records:
    st.info("No results yet. Save a backtest with --save or add a research result.json manifest.")
    st.stop()

kinds = sorted({r.kind for r in records})
selected_kinds = st.sidebar.multiselect("Result types", kinds, default=kinds)
query = st.sidebar.text_input("Search results").casefold().strip()
shown = [
    r
    for r in records
    if r.kind in selected_kinds and query in f"{r.name} {r.id} {r.description}".casefold()
]
if not shown:
    st.info("No results match these filters.")
    st.stop()

st.dataframe(
    pd.DataFrame(
        [
            {
                "Result": r.name,
                "Type": r.kind,
                "Data start": r.start or "not recorded",
                "Data end": r.end or "not recorded",
                "Files updated (UTC)": r.updated,
                "Artifacts": len(r.artifacts),
            }
            for r in shown
        ]
    ),
    hide_index=True,
    width="stretch",
)
st.caption(
    "File update times are separate from the dates covered by the data. "
    "Research entries can contain multiple periods and configurations."
)
by_id = {r.id: r for r in shown}
pick = st.selectbox(
    "Open result", list(by_id), format_func=lambda rid: f"{by_id[rid].name} · {by_id[rid].kind}"
)
record = by_id[pick]
st.subheader(record.name)
missing = [a.label for a in record.artifacts if not a.path.is_file()]
if missing:
    st.warning("Unavailable local artifacts: " + ", ".join(missing))
if record.description:
    st.markdown(record.description)
if record.bundle_id and st.button("Open trade analysis"):
    st.session_state["requested_backtest"] = record.bundle_id
    st.switch_page(str(Path(__file__).with_name("app.py")))

if record.kind == "tests":
    status = record.metadata.get("status", "unknown")
    counts = record.metadata.get("counts", {})
    message = f"Recorded test run: {status} · " + ", ".join(f"{k}: {v}" for k, v in counts.items())
    (st.success if status == "passed" else st.error)(message)
    if record.metadata.get("code_sha256") != code_fingerprint():
        st.warning("Code or configuration has changed since this test run.")
    st.caption("Command: " + record.metadata.get("command", "not recorded"))

reports, files = st.tabs(["Report", "Tables, charts & verification"])
with reports:
    choices = [a for a in record.artifacts if a.role == "report" and a.path.is_file()]
    if choices:
        # Prefer the study's report over protocol and implementation notes.
        choices.sort(key=lambda a: (a.path.name not in {"report.md", "review.md"}, a.label))
        report = st.selectbox(
            "Document", choices, format_func=lambda a: a.label, key=f"{pick}:report"
        )
        root = config.REPO_ROOT / "research"
        if report.path.is_relative_to(root.resolve()):
            st.markdown(notes.linked_markdown(report.path, root))
        else:
            st.markdown(report.path.read_text(encoding="utf-8"))
    else:
        st.info("This result has no written report. Its recorded data is in the next tab.")

with files:
    available = [a for a in record.artifacts if a.role != "report"]
    if available:
        roles = sorted({a.role for a in available})
        role = st.selectbox("Artifact type", ["all", *roles], key=f"{pick}:role")
        search = st.text_input("Find an artifact", key=f"{pick}:artifact_search").casefold()
        available = [
            a
            for a in available
            if (role == "all" or a.role == role) and search in a.label.casefold()
        ]
        priority = {"metrics": 0, "equity": 1, "verification": 2}
        available.sort(
            key=lambda a: (
                priority.get(a.role, 3),
                a.path.name not in {"metrics.csv", "main_metrics.csv"},
                a.label,
            )
        )
        if available:
            artifact = st.selectbox(
                "Artifact", available, format_func=lambda a: a.label, key=f"{pick}:artifact"
            )
            render_artifact(artifact, f"{pick}:{artifact.path}")
        else:
            st.info("No artifacts match these filters.")
    else:
        st.info("No data artifacts recorded.")
