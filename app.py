"""Minimal Streamlit harness to manually exercise the Profiler, Semantic, NaN-Handler, Duplicate-Column, Format-Consistency, and Unified-Remediation agents on an uploaded CSV. Renders an approval gate where the user can Accept, Reject, or Edit-with-feedback each proposed fix."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

from pathlib import Path

import pandas as pd
import streamlit as st

from agents.anomaly_detector import anomaly_detector_node
from agents.duplicate_column import duplicate_column_node
from agents.format_consistency import format_consistency_node
from agents.nan_handler import nan_handler_node
from agents.profiler import profiler_node
from agents.semantic import semantic_node
from agents.apply_fixes import apply_fixes_node
from agents.duplicate_row import duplicate_row_node
from agents.report_generator import report_generator_node
from agents.unified import propose_for_group, unified_node
from state import PipelineState

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
    with st.spinner("Anomaly Detector..."):
        state = anomaly_detector_node(state)
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

format_violations_by_col = {
    r.column_name: sum(
        1 for v in r.violations
        if v.expected_pattern not in (None, "not nullable", "missing value")
    )
    for r in state.validation_reports
}
inference_rows = [
    {
        "column": col,
        "source": info.get("source", "skipped"),
        "profiler_spec": info.get("profiler_spec"),
        "final_spec": info.get("final_spec"),
        "format_violations": format_violations_by_col.get(col, 0),
        "missing": int(state.dataset[col].isna().sum()) if col in state.dataset.columns else 0,
    }
    for col, info in state.inferred_format_specs.items()
]
if inference_rows:
    st.subheader("Format-consistency — per-column inference")
    st.caption(
        "source: 'deterministic' = profiler's spec kept (LLM confirmed or punted); "
        "'deterministic-refined' = LLM upgraded the profiler's spec (e.g. regex -> date); "
        "'llm-only' = profiler found no dominant shape, LLM produced one; "
        "'skipped' = neither found a pattern (treated as free text). "
        "missing = NaN count surfaced as a violation for the unified agent to impute."
    )
    st.dataframe(inference_rows, use_container_width=True)

st.subheader("Anomaly Detection")
if not state.anomaly_reports:
    st.info("No anomalies detected.")
else:
    numeric_reports = [r for r in state.anomaly_reports if r.method == "iqr"]
    cat_reports = [r for r in state.anomaly_reports if r.method == "rare_category"]
    col1, col2 = st.columns(2)
    col1.metric("Columns with numeric outliers", len(numeric_reports))
    col2.metric("Columns with rare categories", len(cat_reports))

    if numeric_reports:
        st.markdown("#### Numeric Outliers (IQR)")
        for r in numeric_reports:
            with st.expander(f"`{r.column_name}` — {r.stats.get('detected', len(r.anomalies))} outliers"):
                if r.comment:
                    st.info(r.comment)
                c1, c2, c3 = st.columns(3)
                c1.metric("Q1", r.stats.get("q1"))
                c2.metric("Q3", r.stats.get("q3"))
                c3.metric("IQR", r.stats.get("iqr"))
                c1.metric("Lower bound", r.stats.get("lower_bound"))
                c2.metric("Upper bound", r.stats.get("upper_bound"))
                if r.anomalies:
                    st.caption("Sample outlier values (up to 10):")
                    st.dataframe(
                        pd.DataFrame([{"row": a.row_index, "value": a.value} for a in r.anomalies[:10]]),
                        use_container_width=True,
                        hide_index=True,
                    )

    if cat_reports:
        st.markdown("#### Rare Categories")
        for r in cat_reports:
            with st.expander(f"`{r.column_name}` — {r.stats.get('detected', len(r.anomalies))} rare value(s) out of {r.stats.get('distinct_values', '?')} distinct"):
                if r.comment:
                    st.info(r.comment)
                top = r.stats.get("top_values", [])
                if top:
                    st.caption("Most common values:")
                    st.dataframe(
                        pd.DataFrame(top).rename(columns={"value": "Value", "count": "Count", "pct": "%"}),
                        use_container_width=True,
                        hide_index=True,
                    )
                if r.anomalies:
                    st.caption(f"Rare values (threshold: < {r.stats.get('threshold')} occurrences):")
                    st.dataframe(
                        pd.DataFrame([{"value": a.value, "reason": a.reason} for a in r.anomalies]),
                        use_container_width=True,
                        hide_index=True,
                    )


def _group_id_of(fix_id: str) -> str:
    return fix_id.split("_", 1)[0]


def _repropose(group_id: str, feedback: str) -> None:
    s: PipelineState = st.session_state.pipeline_state
    group = s.fix_groups.get(group_id, [])
    if not group:
        return
    from agents.unified import _specs_by_col
    new_proposals = propose_for_group(
        group_id,
        group,
        {p.column_name: p for p in s.payload},
        {r.column_name: r for r in s.validation_reports},
        s.dataset,
        s.baseline,
        value_corrections=s.value_corrections,
        feedback=feedback,
        specs_by_col=_specs_by_col(s.inferred_format_specs),
        imputation_hints=s.imputation_hints,
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
        st.code(proposal.code, language="text")

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

if accepted and st.button("Apply accepted fixes"):
    before_df = state.dataset.copy()
    with st.spinner("Executing fixes..."):
        applied_state = apply_fixes_node(
            state.model_copy(update={"approved_fix_ids": [p.id for p in accepted]})
        )
    st.session_state.pipeline_state = applied_state
    st.session_state.execution = {
        "applied": applied_state.applied_fix_ids,
        "rejected": applied_state.errors,
        "before": before_df,
    }
    st.rerun()

execution = st.session_state.execution
if execution is not None:
    st.subheader("Execution result")
    st.json({"applied": execution.get("applied", []), "rejected": execution.get("rejected", [])})
    before_df = execution["before"]
    after_df = st.session_state.pipeline_state.dataset
    diff = [
        {
            "column": c,
            "nans_before": int(before_df[c].isna().sum()),
            "nans_after": int(after_df[c].isna().sum()) if c in after_df.columns else None,
            "uniques_before": int(before_df[c].nunique(dropna=True)),
            "uniques_after": int(after_df[c].nunique(dropna=True)) if c in after_df.columns else None,
        }
        for c in before_df.columns
    ]
    st.caption(f"Before: {before_df.shape[0]} x {before_df.shape[1]}  |  After: {after_df.shape[0]} x {after_df.shape[1]}")
    st.dataframe(diff, use_container_width=True)
    st.subheader("Cleaned dataset preview")
    st.dataframe(after_df.head(20))


final_state: PipelineState = st.session_state.pipeline_state
if final_state is not None and final_state.dataset is not None:
    st.divider()
    st.subheader("Download")
    st.caption(
        "Available as soon as the pipeline has run. Before approving any fix this is the "
        "dataset as the detection stages left it; after approving, it includes the applied "
        "remediations. The full report also runs the duplicate-row pass and writes the PDF "
        "and JSON next to the dataset."
    )
    name = Path(final_state.dataset_path or "dataset").stem
    applied_count = len(final_state.applied_fix_ids)
    pending_count = len([p for p in final_state.proposed_fixes if p.id not in final_state.applied_fix_ids])
    suffix = "cleaned" if applied_count else "processed"

    if applied_count:
        st.success(f"{applied_count} fix applied, {len(final_state.change_log)} cells changed.")
    else:
        st.warning(
            "No fix has been applied yet: this file still contains every violation the "
            "pipeline detected. Accept the proposals above and press Apply first."
        )
    if pending_count:
        st.caption(f"{pending_count} proposal(s) not applied.")

    columns = st.columns(3)
    columns[0].download_button(
        f"Dataset ({suffix}, {applied_count} fix applied)",
        final_state.dataset.to_csv(index=False).encode("utf-8"),
        file_name=f"{name}.{suffix}.csv",
        mime="text/csv",
    )
    if final_state.change_log:
        columns[1].download_button(
            f"Change log ({len(final_state.change_log)} cells)",
            pd.DataFrame(final_state.change_log).to_csv(index=False).encode("utf-8"),
            file_name=f"{name}.changes.csv",
            mime="text/csv",
        )
    if columns[2].button("Generate full report"):
        with st.spinner("Deduplicating rows and writing the report..."):
            reported = report_generator_node(duplicate_row_node(final_state))
        st.session_state.pipeline_state = reported
        st.success(f"Report written next to {reported.dataset_path or 'the dataset'}")

    if final_state.change_log:
        st.subheader("What changed, cell by cell")
        st.dataframe(pd.DataFrame(final_state.change_log), use_container_width=True)
