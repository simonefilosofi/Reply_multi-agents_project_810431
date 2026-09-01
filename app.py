"""Streamlit front end for the NoiPA data-quality pipeline, and the human approval gate the
Unified Remediation agent's proposals must pass through. The run is driven node by node so each
stage's progress is visible, and the result is laid out as four views - what arrived, what was
found, what is proposed, and what was produced - rather than as one column of raw state, because
the reviewer's job is to decide on a handful of proposals and everything else is context for that
decision. The detailed per-stage output every agent produces is kept, one expander down, for
anyone who wants to audit the run rather than approve it."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)

import time
from pathlib import Path

import pandas as pd
import streamlit as st

from agents.anomaly_detector import anomaly_detector_node
from agents.apply_fixes import apply_fixes_node
from agents.auto_remediation import auto_remediation_node
from agents.baseline_builder import baseline_builder_node
from agents.duplicate_column import duplicate_column_node
from agents.duplicate_row import duplicate_row_node
from agents.format_consistency import format_consistency_node
from agents.nan_handler import nan_handler_node
from agents.profiler import profiler_node
from agents.report_generator import output_path, report_generator_node
from agents.semantic import semantic_node
from agents.unified import propose_for_group, unified_node
from state import PipelineState
from tools.change_log import column_diff
from tools.operations import operations_as_python

st.set_page_config(
    page_title="NoiPA Data Quality",
    layout="wide",
    initial_sidebar_state="expanded",
)

_STAGES = (
    ("Baseline", baseline_builder_node),
    ("Profiler", profiler_node),
    ("Semantic", semantic_node),
    ("Completeness", nan_handler_node),
    ("Duplicate columns", duplicate_column_node),
    ("Format consistency", format_consistency_node),
    ("Auto-remediation", auto_remediation_node),
    ("Anomalies", anomaly_detector_node),
    ("Remediation proposals", unified_node),
)

_STYLE = """
<style>
:root {
  --ink: #0b3d0b; --accent: #02b900; --accent-soft: #35c733; --mid: #67d566;
  --muted: #4a7a4a; --line: #9ae399; --wash: #ccf1cc;
  --inactive-ink: #6f6f6f; --inactive-wash: #f1f1f1;
}
.block-container { padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }
h1, h2, h3 { color: var(--ink); font-weight: 650; letter-spacing: -0.01em; }
h1 { font-size: 1.85rem; margin-bottom: .1rem; }
h2 { font-size: 1.2rem; margin-top: .4rem; }
h3 { font-size: 1rem; }

.lede { color: var(--muted); font-size: .93rem; margin: 0 0 1.4rem; max-width: 70ch; }
.eyebrow { color: var(--muted); font-size: .72rem; letter-spacing: .1em;
           text-transform: uppercase; font-weight: 600; margin-bottom: .35rem; }

div[data-testid="stMetric"] {
  background: #fff; border: 1px solid var(--line); border-radius: 10px;
  padding: .8rem .95rem;
}
div[data-testid="stMetric"] label p { color: var(--muted) !important; font-size: .74rem !important;
  letter-spacing: .04em; text-transform: uppercase; font-weight: 600; }
div[data-testid="stMetricValue"] { font-size: 1.5rem; color: var(--ink); font-weight: 650; }

.stTabs [data-baseweb="tab-list"] { gap: .3rem; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] {
  height: 42px; padding: 0 1.1rem; background: transparent; color: var(--muted);
  font-weight: 600; font-size: .88rem;
}
.stTabs [aria-selected="true"] { color: var(--ink); border-bottom: 2px solid var(--accent); }

div[data-testid="stExpander"] { border: 1px solid var(--line); border-radius: 10px;
  background: #fff; margin-bottom: .55rem; }
div[data-testid="stExpander"] summary { font-weight: 600; color: var(--ink); }

.card { background: #fff; border: 1px solid var(--line); border-radius: 10px;
        padding: 1rem 1.15rem; height: 100%; }
.card .t { font-weight: 650; color: var(--ink); margin-bottom: .3rem; font-size: .95rem; }
.card .d { color: var(--muted); font-size: .84rem; line-height: 1.45; }

.chip { display: inline-block; padding: .12rem .55rem; border-radius: 999px;
        font-size: .7rem; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.chip.ok { background: var(--wash); color: var(--ink); box-shadow: inset 2px 0 0 var(--accent); }
.chip.no { background: var(--inactive-wash); color: var(--inactive-ink); }
.chip.wait { background: var(--inactive-wash); color: var(--inactive-ink); box-shadow: inset 2px 0 0 var(--mid); }

.stage { display: flex; justify-content: space-between; font-size: .8rem;
         padding: .22rem 0; border-bottom: 1px dotted var(--line); }
.stage .n { color: var(--ink); }
.stage .s { color: var(--muted); font-variant-numeric: tabular-nums; }

</style>
"""
st.markdown(_STYLE, unsafe_allow_html=True)

for key, default in (
    ("pipeline_state", None), ("timings", {}), ("fix_decisions", {}),
    ("editing", {}), ("execution", None), ("report", None), ("source_name", ""),
):
    st.session_state.setdefault(key, default)


def _run(frame: pd.DataFrame, name: str) -> PipelineState:
    """Drives the nodes in order, naming each as it starts so a long run is legible."""
    state = PipelineState(dataset=frame, dataset_path=name)
    timings: dict[str, float] = {}
    with st.status("Running the pipeline", expanded=True) as status:
        for label, node in _STAGES:
            status.update(label=f"{label} ...")
            started = time.time()
            state = node(state)
            timings[label] = time.time() - started
            st.write(f"{label} - {timings[label]:.1f}s")
        status.update(label=f"Completed in {sum(timings.values()):.0f}s", state="complete",
                      expanded=False)
    st.session_state.timings = timings
    return state


def _read_report(reported: PipelineState) -> dict:
    """Reads back the three renderings the report node just wrote. The PDF is absent when no
    browser was available to print it, which is not an error: the HTML carries the same page."""
    out = output_path(reported)
    report = {"stem": out.stem, "md": out.with_suffix(".md").read_text(encoding="utf-8")}
    for extension, mode in (("html", "r"), ("pdf", "rb")):
        path = out.with_suffix(f".{extension}")
        report[extension] = (
            path.read_text(encoding="utf-8") if mode == "r" else path.read_bytes()
        ) if path.exists() else None
    return report


def _violation_totals(state: PipelineState) -> dict[str, int]:
    totals: dict[str, int] = {}
    for report in state.validation_reports:
        for violation in report.violations:
            totals[violation.kind] = totals.get(violation.kind, 0) + (
                violation.affected_rows if violation.kind == "completeness" else 1
            )
    return totals


def _card(title: str, detail: str) -> str:
    return f"<div class='card'><div class='t'>{title}</div><div class='d'>{detail}</div></div>"


def _repropose(group_id: str, feedback: str) -> None:
    current: PipelineState = st.session_state.pipeline_state
    group = current.fix_groups.get(group_id, [])
    if not group:
        return
    from agents.unified import _specs_by_col

    replacements = propose_for_group(
        group_id,
        group,
        {p.column_name: p for p in current.payload},
        {r.column_name: r for r in current.validation_reports},
        current.dataset,
        current.baseline,
        value_corrections=current.value_corrections,
        feedback=feedback,
        specs_by_col=_specs_by_col(current.inferred_format_specs),
        imputation_hints=current.imputation_hints,
    ).proposals
    kept = [p for p in current.proposed_fixes if p.group_id != group_id]
    st.session_state.pipeline_state = current.model_copy(
        update={"proposed_fixes": kept + replacements}
    )
    for proposal in current.proposed_fixes:
        if proposal.group_id == group_id:
            st.session_state.fix_decisions.pop(proposal.id, None)
            st.session_state.editing.pop(proposal.id, None)


with st.sidebar:
    st.markdown("<div class='eyebrow'>NoiPA</div>", unsafe_allow_html=True)
    st.markdown("## Data Quality")
    uploaded = st.file_uploader("Dataset", type=["csv"], label_visibility="collapsed")

    if uploaded is not None:
        frame = pd.read_csv(uploaded)
        st.caption(f"{uploaded.name}")
        facts = st.columns(2)
        facts[0].metric("Rows", f"{frame.shape[0]:,}")
        facts[1].metric("Columns", frame.shape[1])
        if st.button("Run pipeline", type="primary", use_container_width=True):
            st.session_state.source_name = uploaded.name
            st.session_state.pipeline_state = None
            st.session_state.fix_decisions = {}
            st.session_state.editing = {}
            st.session_state.execution = None
            st.session_state.report = None
            st.session_state.pending_run = frame
            st.rerun()

    if st.session_state.timings:
        st.divider()
        st.markdown("<div class='eyebrow'>Stages</div>", unsafe_allow_html=True)
        st.markdown("".join(
            f"<div class='stage'><span class='n'>{label}</span>"
            f"<span class='s'>{seconds:.1f}s</span></div>"
            for label, seconds in st.session_state.timings.items()
        ), unsafe_allow_html=True)

    reported: PipelineState | None = st.session_state.pipeline_state
    if reported is not None and reported.reliability:
        st.divider()
        st.markdown("<div class='eyebrow'>Reliability</div>", unsafe_allow_html=True)
        delivered = reported.reliability["as_delivered"]
        st.metric(
            "As delivered",
            f"{delivered['after']['score']:.3f}",
            delta=f"{delivered['after']['score'] - delivered['before']['score']:+.3f}",
        )

if st.session_state.get("pending_run") is not None:
    queued = st.session_state.pop("pending_run")
    st.markdown(f"# {st.session_state.source_name}")
    st.session_state.pipeline_state = _run(queued, st.session_state.source_name)
    st.rerun()

state: PipelineState | None = st.session_state.pipeline_state

if state is None:
    st.markdown("# Data quality for NoiPA datasets")
    st.markdown(
        "<p class='lede'>A multi-agent pipeline that reads a raw CSV, measures it against the "
        "NoiPA schema registry and against itself, proposes corrections for a person to approve, "
        "and produces a data quality report. Upload a file in the sidebar to begin.</p>",
        unsafe_allow_html=True,
    )
    areas = st.columns(5)
    for column, (title, detail) in zip(areas, (
        ("Schema", "Type per column, and names against the registry's convention."),
        ("Completeness", "Nulls and the placeholders standing in for them, per column and row."),
        ("Consistency", "Cross-column rules, format drift, duplicate rows and columns."),
        ("Anomalies", "Statistical outliers and rare categories, reported not corrected."),
        ("Remediation", "Every issue carries an action, or a reason none exists."),
    )):
        column.markdown(_card(title, detail), unsafe_allow_html=True)
    st.stop()

frame_now = state.dataset
totals = _violation_totals(state)
accepted = [p for p in state.proposed_fixes if st.session_state.fix_decisions.get(p.id) == "accepted"]
rejected = [p for p in state.proposed_fixes if st.session_state.fix_decisions.get(p.id) == "rejected"]
pending = [p for p in state.proposed_fixes if st.session_state.fix_decisions.get(p.id) is None]

st.markdown(f"# {st.session_state.source_name or 'Dataset'}")
st.markdown(
    f"<p class='lede'>Domain {state.detected_domain or 'not detected'} - language "
    f"{state.detected_language or 'not detected'}. "
    f"{len(state.proposed_fixes)} proposal(s) awaiting review.</p>",
    unsafe_allow_html=True,
)

overview, findings, review, report_tab = st.tabs(
    ["Overview", "Findings", "Review and apply", "Report"]
)

with overview:
    head = st.columns(5)
    head[0].metric("Rows", f"{frame_now.shape[0]:,}")
    head[1].metric("Columns", frame_now.shape[1])
    head[2].metric("Null cells", f"{int(frame_now.isna().sum().sum()):,}")
    head[3].metric("Applied automatically", len(state.auto_remediations))
    head[4].metric("Proposals", len(state.proposed_fixes))

    st.markdown("### What was found")
    areas = st.columns(5)
    for column, (label, value) in zip(areas, (
        ("Schema", totals.get("schema", 0)),
        ("Completeness", totals.get("completeness", 0)),
        ("Consistency", totals.get("consistency", 0)),
        ("Format", totals.get("format", 0)),
        ("Anomalies", sum(len(r.anomalies) for r in state.anomaly_reports)),
    )):
        column.metric(label, f"{value:,}")

    completeness = state.completeness or {}
    by_column = completeness.get("by_column") or {}
    if by_column:
        st.markdown("### Fill rate by column")
        fill = pd.DataFrame([
            {"column": name, "filled": round(info["completeness"] * 100, 1),
             "nulls": info["nulls"]}
            for name, info in sorted(by_column.items(), key=lambda kv: kv[1]["completeness"])
        ])
        st.dataframe(
            fill, use_container_width=True, hide_index=True,
            column_config={"filled": st.column_config.ProgressColumn(
                "filled", format="%.1f%%", min_value=0, max_value=100)},
        )

    st.markdown("### The data as it now stands")
    st.dataframe(frame_now.head(25), use_container_width=True)

with findings:
    if state.duplicate_resolutions:
        st.markdown("### Duplicate columns")
        st.dataframe(pd.DataFrame([
            {"kept as": r.canonical_name, "data from": r.data_survivor,
             "removed": ", ".join(r.dropped), "backfilled": r.cells_backfilled,
             "overwritten": sum(r.cells_overwritten.values())}
            for r in state.duplicate_resolutions
        ]), use_container_width=True, hide_index=True)

    if state.auto_remediations:
        st.markdown("### Corrections applied without asking")
        st.caption(
            "Values the data determines on its own. They are deductions rather than judgement "
            "calls, so they are applied before the gate and recorded in the change log."
        )
        st.dataframe(pd.DataFrame(state.auto_remediations),
                     use_container_width=True, hide_index=True)

    if state.anomaly_reports:
        st.markdown("### Anomalies")
        st.caption("An outlier is unusual, which is not the same as wrong. These are reported, "
                   "and left for a person to judge unless the value is impossible.")
        numeric = [r for r in state.anomaly_reports if r.method == "iqr"]
        categorical = [r for r in state.anomaly_reports if r.method == "rare_category"]
        for report in numeric + categorical:
            found = report.stats.get("detected", len(report.anomalies))
            kind = "outliers" if report.method == "iqr" else "rare values"
            with st.expander(f"{report.column_name} - {found:,} {kind}"):
                if report.comment:
                    st.caption(report.comment)
                if report.method == "iqr":
                    bounds = st.columns(4)
                    for slot, key in zip(bounds, ("q1", "q3", "lower_bound", "upper_bound")):
                        slot.metric(key.replace("_", " "), report.stats.get(key))
                if report.anomalies:
                    st.dataframe(
                        pd.DataFrame([{"row": a.row_index, "value": a.value, "reason": a.reason}
                                      for a in report.anomalies[:25]]),
                        use_container_width=True, hide_index=True,
                    )

    if state.unaddressed_violations:
        st.markdown("### Carried without a corrective action")
        st.dataframe(pd.DataFrame([
            {"columns": ", ".join(u.columns), "rows": u.affected_rows or None, "why": u.reason}
            for u in state.unaddressed_violations
        ]), use_container_width=True, hide_index=True)

    with st.expander("Diagnostics - the full state each agent produced"):
        st.caption("Everything the run recorded, for auditing rather than approving.")
        st.markdown("**Semantic payload**")
        st.dataframe(pd.DataFrame([
            {"column": p.column_name, "dtype": p.dtype, "canonical": p.canonical_hint,
             "placeholders": ", ".join(str(v) for v in p.placeholders),
             "related": ", ".join(p.related_columns)}
            for p in state.payload
        ]), use_container_width=True, hide_index=True)
        if state.inferred_format_specs:
            st.markdown("**Inferred format specs**")
            st.dataframe(pd.DataFrame([
                {"column": column, "source": info.get("source", "skipped"),
                 "final spec": str(info.get("final_spec"))}
                for column, info in state.inferred_format_specs.items()
            ]), use_container_width=True, hide_index=True)
        if state.imputation_hints:
            st.markdown("**Mined imputation hints**")
            st.dataframe(pd.DataFrame([
                {"column": column, "from": ", ".join(hint.predictor_columns),
                 "purity": round(hint.purity, 4), "coverage": round(hint.coverage, 4)}
                for column, hint in state.imputation_hints.items()
            ]), use_container_width=True, hide_index=True)
        if state.errors:
            st.markdown("**Errors recorded**")
            for error in state.errors:
                st.warning(error)

with review:
    if not state.proposed_fixes:
        st.info("No remediation proposed. Either nothing was detected, or every violation was "
                "declared unaddressable.")
    else:
        counts = st.columns(3)
        counts[0].metric("Accepted", len(accepted))
        counts[1].metric("Rejected", len(rejected))
        counts[2].metric("Awaiting a decision", len(pending))

    for proposal in state.proposed_fixes:
        decision = st.session_state.fix_decisions.get(proposal.id)
        chip = {"accepted": "<span class='chip ok'>accepted</span>",
                "rejected": "<span class='chip no'>rejected</span>"}.get(
            decision, "<span class='chip wait'>pending</span>")
        with st.expander(f"{proposal.description}", expanded=decision is None):
            st.markdown(
                f"{chip} &nbsp; <code>{proposal.id}</code> &nbsp; affects "
                f"<code>{', '.join(proposal.affected_columns) or 'nothing'}</code> &nbsp; "
                f"about {proposal.estimated_rows_affected:,} row(s)",
                unsafe_allow_html=True,
            )
            st.markdown(f"_{proposal.rationale}_")
            if proposal.depends_on:
                st.caption(f"Depends on {', '.join(proposal.depends_on)}")
            generated = [o for o in proposal.operations if o.kind == "apply_generated_function"]
            st.code(operations_as_python(proposal.operations), language="python")
            st.caption(
                "The cleaning function above is the code that will run, written by the model for "
                "this column. It was refused any import outside re, datetime, decimal and math, "
                "then executed against this column's own conforming and violating values before "
                "reaching you."
                if generated else
                "Equivalent pandas expression, shown so you can see exactly what the proposal "
                "does. The pipeline executes the typed operations, not this text."
            )
            actions = st.columns([1, 1, 1, 5])
            if actions[0].button("Accept", key=f"acc_{proposal.id}", use_container_width=True):
                st.session_state.fix_decisions[proposal.id] = "accepted"
                st.session_state.editing.pop(proposal.id, None)
                st.rerun()
            if actions[1].button("Reject", key=f"rej_{proposal.id}", use_container_width=True):
                st.session_state.fix_decisions[proposal.id] = "rejected"
                st.session_state.editing.pop(proposal.id, None)
                st.rerun()
            if actions[2].button("Revise", key=f"edt_{proposal.id}", use_container_width=True):
                st.session_state.editing[proposal.id] = True
                st.rerun()

            if st.session_state.editing.get(proposal.id):
                feedback = st.text_area(
                    "What should the model change?",
                    key=f"fb_{proposal.id}",
                    placeholder="e.g. do not impute eta_max from sesso, use eta_min's mapping",
                )
                if st.button("Re-propose", key=f"rep_{proposal.id}") and feedback.strip():
                    with st.spinner("Re-proposing"):
                        _repropose(proposal.group_id, feedback.strip())
                    st.rerun()

    if accepted:
        st.divider()
        if st.button(f"Apply {len(accepted)} accepted fix(es)", type="primary"):
            before = state.dataset.copy()
            with st.spinner("Executing"):
                applied = apply_fixes_node(
                    state.model_copy(update={"approved_fix_ids": [p.id for p in accepted]})
                )
            st.session_state.pipeline_state = applied
            st.session_state.execution = {"applied": applied.applied_fix_ids,
                                          "refused": applied.errors, "before": before}
            st.rerun()

    execution = st.session_state.execution
    if execution is not None:
        st.divider()
        st.markdown("### What the run applied")
        result = st.columns(2)
        result[0].metric("Fixes applied", len(execution["applied"]))
        result[1].metric("Refused", len(execution["refused"]))
        for refusal in execution["refused"]:
            st.warning(refusal)
        applied_state = st.session_state.pipeline_state
        before_frame, after_frame = execution["before"], applied_state.dataset
        landed = set(applied_state.applied_fix_ids)
        renames = {
            operation.column: operation.new_name
            for proposal in applied_state.proposed_fixes if proposal.id in landed
            for operation in proposal.operations
            if operation.kind == "rename_column" and operation.new_name
        }
        st.dataframe(pd.DataFrame(column_diff(before_frame, after_frame, renames)),
                     use_container_width=True, hide_index=True)

with report_tab:
    final: PipelineState = st.session_state.pipeline_state
    applied_count = len(final.applied_fix_ids)
    if not applied_count:
        st.warning(
            "No fix has been applied yet, so the file below still carries every violation the "
            "run detected. Accept the proposals under Review and apply them first."
        )
    name = Path(final.dataset_path or "dataset").stem
    downloads = st.columns(3)
    downloads[0].download_button(
        "Dataset (CSV)",
        final.dataset.to_csv(index=False).encode("utf-8"),
        file_name=f"{name}.{'cleaned' if applied_count else 'processed'}.csv",
        mime="text/csv", use_container_width=True,
    )
    if final.change_log:
        downloads[1].download_button(
            f"Change log ({len(final.change_log):,} cells)",
            pd.DataFrame(final.change_log).to_csv(index=False).encode("utf-8"),
            file_name=f"{name}.changes.csv", mime="text/csv", use_container_width=True,
        )
    if downloads[2].button("Generate the full report", type="primary", use_container_width=True):
        with st.spinner("Deduplicating rows and writing the report"):
            produced = report_generator_node(duplicate_row_node(final))
        st.session_state.pipeline_state = produced
        st.session_state.report = _read_report(produced)
        st.rerun()

    report = st.session_state.report
    if not report:
        st.info("The report runs the duplicate-row pass, recomputes the residual violations and "
                "writes Markdown, HTML and PDF beside the dataset.")
    else:
        files = st.columns(3)
        for slot, extension, mime in (
            (files[0], "md", "text/markdown"),
            (files[1], "html", "text/html"),
            (files[2], "pdf", "application/pdf"),
        ):
            content = report.get(extension)
            if content is not None:
                slot.download_button(f"Report ({extension})", content,
                                     file_name=f"{report['stem']}.{extension}", mime=mime,
                                     use_container_width=True)
        if report.get("pdf") is None:
            st.caption("No browser was available to print the PDF. The HTML is one "
                       "self-contained file and prints identically.")
        with st.container(border=True, height=760):
            st.markdown(report["md"], unsafe_allow_html=True)
