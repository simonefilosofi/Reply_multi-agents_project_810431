"""Minimal Streamlit harness to manually exercise the Profiler, Semantic, NaN-Handler, Duplicate-Column, Format-Consistency, and Unified-Remediation agents on an uploaded CSV. Renders an approval gate where the user can Accept, Reject, or Edit-with-feedback each proposed fix."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
import streamlit as st

from agents.duplicate_column import duplicate_column_node
from agents.format_consistency import format_consistency_node
from agents.nan_handler import nan_handler_node
from agents.profiler import profiler_node
from agents.semantic import semantic_node
from agents.unified import propose_for_group, unified_node
from state import PipelineState
from tools.execute_fixes import execute_fixes

st.set_page_config(page_title="NoiPA DQ — pipeline test", layout="wide")
st.title("NoiPA DQ — Profiler, Semantic, NaN, Duplicate-Column, Format, Unified")

st.session_state.setdefault("pipeline_state", None)
st.session_state.setdefault("snapshots", {})
st.session_state.setdefault("fix_decisions", {})
st.session_state.setdefault("editing", {})
st.session_state.setdefault("execution", None)

uploaded = st.file_uploader("Upload a CSV", type=["csv"])
if uploaded is None:
    st.stop()

df = pd.read_csv(uploaded)
st.subheader("Input preview")
st.caption(f"{df.shape[0]} rows x {df.shape[1]} columns")
st.dataframe(df.head(20))

if st.button("Run pipeline"):
    snapshots: dict = {}
    state = PipelineState(dataset=df, dataset_path=uploaded.name)

    with st.spinner("Profiler..."):
        state = profiler_node(state)
    with st.spinner("Semantic..."):
        state = semantic_node(state)
    snapshots["nan_before"] = state.dataset.isna().sum().to_dict()
    with st.spinner("NaN handler..."):
        state = nan_handler_node(state)
    snapshots["nan_after"] = state.dataset.isna().sum().to_dict()
    snapshots["cols_before_dup"] = list(state.dataset.columns)
    snapshots["nan_pre_dup"] = state.dataset.isna().sum().to_dict()
    with st.spinner("Duplicate Column..."):
        state = duplicate_column_node(state)
    snapshots["nan_post_dup"] = state.dataset.isna().sum().to_dict()
    with st.spinner("Format Consistency..."):
        state = format_consistency_node(state)
    with st.spinner("Unified Remediation..."):
        state = unified_node(state)

    st.session_state.pipeline_state = state
    st.session_state.snapshots = snapshots
    st.session_state.fix_decisions = {}
    st.session_state.editing = {}

state: PipelineState | None = st.session_state.pipeline_state
if state is None:
    st.stop()

snapshots = st.session_state.snapshots

st.subheader("Profiler output")
st.json({"detected_domain": state.detected_domain, "detected_language": state.detected_language})

st.subheader("Semantic payload")
st.json([p.model_dump() for p in state.payload])

st.subheader("NaN handler — disguised NaNs replaced")
nan_diff = {
    col: {"before": int(snapshots["nan_before"][col]), "after": int(snapshots["nan_after"][col])}
    for col in snapshots["nan_before"]
    if snapshots["nan_after"][col] != snapshots["nan_before"][col]
} or {"info": "no disguised NaNs were detected"}
st.json(nan_diff)

nullability_issues = [
    {"column": r.column_name, "violations": [v.model_dump() for v in r.violations]}
    for r in state.validation_reports
    if any(v.expected_pattern == "not nullable" for v in r.violations)
]
if nullability_issues:
    st.subheader("Nullability issues — non-nullable columns with NaN")
    st.json(nullability_issues)

dropped = [c for c in snapshots["cols_before_dup"] if c not in state.surviving_columns]
filled = {
    c: int(snapshots["nan_pre_dup"][c] - snapshots["nan_post_dup"][c])
    for c in state.surviving_columns
    if snapshots["nan_pre_dup"].get(c, 0) > snapshots["nan_post_dup"].get(c, 0)
}
st.subheader("Duplicate-Column output")
st.json({
    "surviving_columns": state.surviving_columns,
    "dropped_columns": dropped,
    "gaps_filled_from_siblings": filled,
})
if state.duplicate_resolutions:
    st.subheader("Name election rationales")
    st.json([r.model_dump() for r in state.duplicate_resolutions])
st.caption(f"Dataset after pruning: {state.dataset.shape[0]} rows x {state.dataset.shape[1]} columns")
st.dataframe(state.dataset.head(20))

format_issues = [
    {"column": r.column_name, "violation_count": len(r.violations)}
    for r in state.validation_reports
    if any(v.expected_pattern not in (None, "not nullable") for v in r.violations)
]
if format_issues:
    st.subheader("Format-consistency violations")
    st.json(format_issues)


def _group_id_of(fix_id: str) -> str:
    return fix_id.split("_", 1)[0]


def _repropose(group_id: str, feedback: str) -> None:
    s: PipelineState = st.session_state.pipeline_state
    group = s.fix_groups.get(group_id, [])
    if not group:
        return
    new_proposals = propose_for_group(
        group_id,
        group,
        {p.column_name: p for p in s.payload},
        {r.column_name: r for r in s.validation_reports},
        s.dataset,
        s.baseline,
        value_corrections=s.value_corrections,
        feedback=feedback,
    )
    remaining = [p for p in s.proposed_fixes if _group_id_of(p.id) != group_id]
    st.session_state.pipeline_state = s.model_copy(update={"proposed_fixes": remaining + new_proposals})
    for p in s.proposed_fixes:
        if _group_id_of(p.id) == group_id:
            st.session_state.fix_decisions.pop(p.id, None)
            st.session_state.editing.pop(p.id, None)


st.subheader(f"Approval gate — {len(state.proposed_fixes)} proposed fix(es)")
if not state.proposed_fixes:
    st.info("No remediation proposed. Either no violations were detected, or every violation was declared unaddressable.")

for proposal in state.proposed_fixes:
    decision = st.session_state.fix_decisions.get(proposal.id)
    label = f"{proposal.id} — {proposal.description}"
    if decision:
        label = f"[{decision.upper()}] {label}"
    with st.expander(label, expanded=decision is None):
        cols = st.columns([2, 1, 1])
        cols[0].markdown(f"**Affects:** `{', '.join(proposal.affected_columns) or '—'}`")
        cols[1].markdown(f"**Addresses:** `{', '.join(proposal.addresses_violations) or '—'}`")
        cols[2].markdown(f"**~Rows:** `{proposal.estimated_rows_affected}`")
        if proposal.depends_on:
            st.caption(f"Depends on: {', '.join(proposal.depends_on)}")
        st.markdown(f"_{proposal.rationale}_")
        st.code(proposal.code, language="python")

        btns = st.columns(3)
        if btns[0].button("Accept", key=f"acc_{proposal.id}"):
            st.session_state.fix_decisions[proposal.id] = "accepted"
            st.session_state.editing.pop(proposal.id, None)
            st.rerun()
        if btns[1].button("Reject", key=f"rej_{proposal.id}"):
            st.session_state.fix_decisions[proposal.id] = "rejected"
            st.session_state.editing.pop(proposal.id, None)
            st.rerun()
        if btns[2].button("Edit", key=f"edt_{proposal.id}"):
            st.session_state.editing[proposal.id] = True
            st.rerun()

        if st.session_state.editing.get(proposal.id):
            feedback = st.text_area(
                "What should the LLM change?",
                key=f"fb_{proposal.id}",
                placeholder="e.g. don't impute eta_max from sesso, use eta_min's enum mapping instead",
            )
            if st.button("Re-propose with this feedback", key=f"rep_{proposal.id}"):
                if feedback.strip():
                    with st.spinner("Re-proposing..."):
                        _repropose(_group_id_of(proposal.id), feedback.strip())
                    st.rerun()

accepted = [p for p in state.proposed_fixes if st.session_state.fix_decisions.get(p.id) == "accepted"]
rejected = [p for p in state.proposed_fixes if st.session_state.fix_decisions.get(p.id) == "rejected"]
pending = [p for p in state.proposed_fixes if st.session_state.fix_decisions.get(p.id) is None]

st.subheader("Approval summary")
st.json({
    "accepted": [p.id for p in accepted],
    "rejected": [p.id for p in rejected],
    "pending": [p.id for p in pending],
})
st.caption("Sandboxed execution of accepted fixes is not yet wired in. The next step adds an Executor node that runs the accepted code in E2B and applies the cleaned dataframe back to state.dataset.")
