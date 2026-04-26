"""Streamlit dashboard for the multi-agent data quality pipeline.
Supports multi-dataset upload, full pipeline execution through all four
layers, and an enhanced dashboard with reliability scores, remediation
details, visualizations, agent communication logs, and JSON export."""

import json
import os
import tempfile

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from state_demo.pipeline_state import PipelineState
from agents_demo.ingestion_agent import IngestionAgent
from agents_demo.profiler_agent import ProfilerAgent
from agents_demo.schema_agent import SchemaAgent
from agents_demo.completeness_agent import CompletenessAgent
from agents_demo.duplicate_agent import DuplicateAgent
from agents_demo.anomaly_agent import AnomalyAgent
from agents_demo.consistency_agent import ConsistencyAgent
from agents_demo.constraint_agent import ConstraintAgent
from agents_demo.synthesis_agent import SynthesisAgent
from agents_demo.remediation_agent import RemediationAgent
from agents_demo.report_agent import ReportAgent

load_dotenv()

st.set_page_config(page_title="Data Quality Pipeline", layout="wide")
st.title("Multi-Agent Data Quality Pipeline")

# ── Pipeline step registry ─────────────────────────────────────────────────────
# (AgentClass, internal_key, display_name, prompt)
PIPELINE_STEPS = [
    (IngestionAgent,    "ingestion",    "Ingestion",
     "Load and ingest the dataset."),
    (ProfilerAgent,     "profiler",     "Profiler",
     "Classify all columns by semantic type and generate a dataset fingerprint."),
    (SchemaAgent,       "schema",       "Schema",
     "Validate column data types and naming conventions."),
    (CompletenessAgent, "completeness", "Completeness",
     "Detect missing, empty, and placeholder values across all columns."),
    (DuplicateAgent,    "duplicate",    "Duplicates",
     "Identify duplicate rows, redundant column pairs, and key-collision records."),
    (AnomalyAgent,      "anomaly",      "Anomaly",
     "Detect statistical outliers and rare categories."),
    (ConsistencyAgent,  "consistency",  "Consistency",
     "Check date format consistency, case consistency, and conditional completeness."),
    (ConstraintAgent,   "constraint",   "Constraints",
     "Enforce domain constraints, format patterns, and numeric corruption checks."),
    (SynthesisAgent,    "synthesis",    "Synthesis",
     "Synthesize all findings, identify cross-cutting patterns, compute reliability."),
    (RemediationAgent,  "remediation",  "Remediation",
     "Apply automated fixes and flag issues requiring human review."),
    (ReportAgent,       "report",       "Report",
     "Compile the final data quality report with visualizations."),
]

_REPORT_ATTRS = {
    "schema":       "schema_report",
    "completeness": "completeness_report",
    "duplicate":    "duplicate_report",
    "anomaly":      "anomaly_report",
    "consistency":  "consistency_report",
    "constraint":   "constraint_report",
}


def _step_info(state: PipelineState, key: str) -> str:
    """Return a short info string for the status table after an agent completes."""
    if key == "ingestion":
        m = state.ingestion_meta
        return f"{m.get('rows', '?')} rows × {m.get('columns', '?')} cols"
    if key == "profiler":
        domain = state.dataset_fingerprint.get("domain", "?")
        return domain[:45] + ("…" if len(domain) > 45 else "")
    if key in _REPORT_ATTRS:
        report = getattr(state, _REPORT_ATTRS[key], {})
        n = report.get("total_issues", 0)
        return f"{n} issue{'s' if n != 1 else ''}"
    if key == "synthesis":
        return f"reliability {state.reliability_score_before:.0f}/100 (pre-fix)"
    if key == "remediation":
        auto   = sum(1 for f in state.fix_log if "auto"   in f.get("action", ""))
        flagged = sum(1 for f in state.fix_log if f.get("action") == "flagged_for_review")
        llm    = sum(1 for f in state.fix_log if f.get("action") == "auto_fixed_by_llm")
        return f"{auto} fixed ({llm} by LLM), {flagged} flagged"
    if key == "report":
        return f"reliability {state.reliability_score_after:.0f}/100 (post-fix)"
    return "—"


def run_pipeline(file_obj):
    suffix = "." + file_obj.name.rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_obj.read())
        tmp_path = tmp.name

    state = PipelineState(source_path=tmp_path)
    n = len(PIPELINE_STEPS)

    # ── Live progress UI ───────────────────────────────────────────────────────
    st.markdown("#### Pipeline Progress")
    col_table, col_log = st.columns([2, 3])

    status_list = ["⏳ Pending"] * n
    info_list   = ["—"] * n

    with col_table:
        st.caption("Agent Status")
        table_ph = st.empty()

    with col_log:
        st.caption("Execution Log")
        log_ph = st.empty()

    log_lines: list = []

    def _redraw_table():
        df = pd.DataFrame({
            "Agent":  [s[2] for s in PIPELINE_STEPS],
            "Status": status_list,
            "Info":   info_list,
        })
        table_ph.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Agent":  st.column_config.TextColumn("Agent",  width="small"),
                "Status": st.column_config.TextColumn("Status", width="medium"),
                "Info":   st.column_config.TextColumn("Info",   width="large"),
            },
        )

    def _redraw_log():
        log_ph.code("\n".join(log_lines) if log_lines else "— waiting for first agent —")

    _redraw_table()
    _redraw_log()

    # ── Sequential agent execution ─────────────────────────────────────────────
    for i, (AgentClass, key, display_name, prompt) in enumerate(PIPELINE_STEPS):
        status_list[i] = "🔄 Running…"
        _redraw_table()

        prev_len = len(state.agent_log)
        AgentClass(state).run(prompt=prompt)
        new_entries = state.agent_log[prev_len:]

        status_list[i] = "✅ Done"
        info_list[i]   = _step_info(state, key)
        _redraw_table()

        # Append this agent's log block
        sep = "─" * 56
        log_lines += [sep, f"  {display_name}", sep]
        for e in new_entries:
            phase = e["phase"].upper()
            msg   = e["message"]
            if len(msg) > 320:
                msg = msg[:317] + "…"
            log_lines.append(f"  [{phase:<8}] {msg}")
        log_lines.append("")
        _redraw_log()

    # ── Cleanup & chart extraction ─────────────────────────────────────────────
    os.unlink(tmp_path)

    chart_images = {}
    for path in state.final_report.get("visualizations", []):
        if path and os.path.exists(path):
            with open(path, "rb") as img_file:
                chart_images[os.path.basename(path)] = img_file.read()

    return state, chart_images


# ── Results display ────────────────────────────────────────────────────────────

def display_results(state, chart_images, dataset_name):
    st.header("Reliability Score")
    before = state.reliability_score_before
    after  = state.reliability_score_after
    delta  = after - before

    col1, col2, col3 = st.columns(3)
    col1.metric("Before Remediation", f"{before}/100")
    col2.metric("After Remediation",  f"{after}/100", delta=f"{delta:+.1f}")
    col3.metric("Improvement",        f"{delta:+.1f} points")

    st.header("Dataset Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Rows",    state.ingestion_meta.get("rows", "-"))
    col2.metric("Columns", state.ingestion_meta.get("columns", "-"))
    col3.metric("Format",  state.source_format.upper())

    st.dataframe(state.df_raw.head(10), use_container_width=True)

    st.header("Dataset Profile")
    fp = state.dataset_fingerprint
    col1, col2 = st.columns(2)
    col1.markdown(f"**Domain:** {fp.get('domain', '-')}")
    col1.markdown(f"**Language:** {fp.get('language', '-')}")
    col2.markdown(f"**ID columns:** {', '.join(fp.get('id_columns', [])) or '-'}")
    col2.markdown(f"**Date columns:** {', '.join(fp.get('date_columns', [])) or '-'}")

    st.header("Executive Summary")
    st.info(state.final_report.get("executive_summary", state.synthesis_summary))

    issues = state.prioritized_issues
    high   = sum(1 for i in issues if i["severity"] == "high")
    medium = sum(1 for i in issues if i["severity"] == "medium")
    low    = sum(1 for i in issues if i["severity"] == "low")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Issues", len(issues))
    col2.metric("High",   high)
    col3.metric("Medium", medium)
    col4.metric("Low",    low)

    st.subheader("Prioritized Issues")
    if issues:
        st.dataframe(issues, use_container_width=True)

    st.header("Remediation Results")
    fix_log       = state.fix_log
    auto_fixed    = [f for f in fix_log if f["action"] == "auto_fixed"]
    auto_fixed_llm = [f for f in fix_log if f["action"] == "auto_fixed_by_llm"]
    flagged       = [f for f in fix_log if f["action"] == "flagged_for_review"]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Actions",     len(fix_log))
    col2.metric("Auto-Fixed",        len(auto_fixed))
    col3.metric("Fixed by LLM",      len(auto_fixed_llm))
    col4.metric("Flagged for Review", len(flagged))

    if auto_fixed:
        st.subheader("Auto-Fixed Issues")
        st.dataframe(
            pd.DataFrame(auto_fixed)[
                ["issue_type", "column", "description", "rows_affected"]
            ],
            use_container_width=True,
        )

    if auto_fixed_llm:
        st.subheader("Fixed by LLM Code Generation")
        st.dataframe(
            pd.DataFrame(auto_fixed_llm)[
                ["issue_type", "column", "description", "rows_affected", "attempts"]
            ],
            use_container_width=True,
        )

    if flagged:
        st.subheader("Flagged for Review")
        st.dataframe(
            pd.DataFrame(flagged)[
                ["issue_type", "column", "description", "rows_affected"]
            ],
            use_container_width=True,
        )

    human_review = state.human_review_items
    if human_review:
        st.subheader(f"Requires Human Review ({len(human_review)} item(s))")
        st.warning(
            "The following issues could not be fixed automatically after "
            f"{len(human_review)} attempt(s) and require manual intervention."
        )
        for item in human_review:
            with st.expander(
                f"[{item['issue']['severity'].upper()}] "
                f"{item['column']} — {item['issue']['type']}"
            ):
                st.markdown(f"**Issue:** {item['issue'].get('detail', '-')}")
                st.markdown(f"**Reason:** {item['reason']}")
                st.markdown(f"**Attempts:** {item['attempts']}")
                if item["last_error"]:
                    st.markdown(f"**Last error:** `{item['last_error']}`")
                if item["last_generated_code"]:
                    st.code(item["last_generated_code"], language="python")

    if state.df_cleaned is not None and not state.df_cleaned.empty:
        st.subheader("Cleaned Dataset Preview")
        rows_raw   = len(state.df_raw)
        rows_clean = len(state.df_cleaned)
        cols_raw   = len(state.df_raw.columns)
        cols_clean = len(state.df_cleaned.columns)
        c1, c2 = st.columns(2)
        c1.metric("Rows",    f"{rows_raw} → {rows_clean}",  delta=rows_clean - rows_raw)
        c2.metric("Columns", f"{cols_raw} → {cols_clean}", delta=cols_clean - cols_raw)
        st.dataframe(state.df_cleaned.head(10), use_container_width=True)

    st.header("Visualizations")
    chart_order = [
        ("issue_severity_distribution.png", "Issue Severity Distribution"),
        ("issues_by_agent.png",             "Issues by Agent"),
        ("completeness_heatmap.png",        "Completeness Heatmap"),
        ("reliability_before_after.png",    "Reliability Before vs After"),
    ]
    col1, col2 = st.columns(2)
    for idx, (filename, caption) in enumerate(chart_order):
        target = col1 if idx % 2 == 0 else col2
        if filename in chart_images:
            target.image(chart_images[filename], caption=caption, use_container_width=True)

    st.header("Issues by Agent")
    reports = {
        "Schema":       (state.schema_report,       state.schema_summary),
        "Completeness": (state.completeness_report,  state.completeness_summary),
        "Duplicates":   (state.duplicate_report,     state.duplicate_summary),
        "Anomalies":    (state.anomaly_report,        state.anomaly_summary),
        "Consistency":  (state.consistency_report,   state.consistency_summary),
        "Constraints":  (state.constraint_report,    state.constraint_summary),
    }
    for name, (report, summary) in reports.items():
        count = report.get("total_issues", 0)
        with st.expander(f"{name} — {count} issue(s)"):
            if summary:
                st.info(summary)
            agent_issues = report.get("issues", [])
            if agent_issues:
                st.table(agent_issues)
            else:
                st.success("No issues found.")

    st.header("Cross-Agent Insights")
    insights = state.cross_agent_insights
    if insights:
        for ins in insights:
            related = ", ".join(ins.get("related_agents", []))
            st.markdown(
                f"**{ins['insight']}**\n\n"
                f"Related agents: {related}\n\n"
                f"Action: {ins.get('action_taken', '-')}"
            )
            st.divider()
    else:
        st.info("No cross-agent insights generated.")

    with st.expander("Full Agent Communication Log"):
        if state.agent_log:
            st.dataframe(pd.DataFrame(state.agent_log), use_container_width=True)
        else:
            st.info("No agent log entries.")

    st.header("Export")
    report_json = _serialize_report(state.final_report)
    col1, col2 = st.columns(2)
    col1.download_button(
        label="Download Report (JSON)",
        data=report_json,
        file_name=f"data_quality_report_{dataset_name}.json",
        mime="application/json",
    )
    if state.df_cleaned is not None and not state.df_cleaned.empty:
        cleaned_csv = state.df_cleaned.to_csv(index=False).encode("utf-8")
        base_name   = dataset_name.rsplit(".", 1)[0]
        col2.download_button(
            label="Download Cleaned Dataset (CSV)",
            data=cleaned_csv,
            file_name=f"{base_name}_cleaned.csv",
            mime="text/csv",
        )


def _serialize_report(report):
    def default_handler(obj):
        if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)
        if hasattr(obj, "item"):
            return obj.item()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        return str(obj)
    return json.dumps(report, indent=2, default=default_handler)


# ── Main ───────────────────────────────────────────────────────────────────────

uploaded_files = st.file_uploader(
    "Upload one or more datasets",
    type=["csv", "json", "xlsx", "xls", "parquet"],
    accept_multiple_files=True,
)

if uploaded_files:
    if st.button("Run Analysis", type="primary"):
        results = []
        for file_obj in uploaded_files:
            st.divider()
            st.subheader(f"📂 {file_obj.name}")
            state, chart_images = run_pipeline(file_obj)
            results.append((file_obj.name, state, chart_images))
        st.session_state["pipeline_results"] = results

if "pipeline_results" in st.session_state:
    results = st.session_state["pipeline_results"]
    st.divider()

    if len(results) > 1:
        st.header("Multi-Dataset Comparison")
        cols = st.columns(len(results))
        for idx, (name, state, _) in enumerate(results):
            with cols[idx]:
                st.subheader(name)
                before = state.reliability_score_before
                after  = state.reliability_score_after
                st.metric("Before", f"{before}/100")
                st.metric("After",  f"{after}/100", delta=f"{after - before:+.1f}")
                st.metric("Issues Found", len(state.prioritized_issues))
                st.metric("Fixes Applied", len(state.fix_log))

        tabs = st.tabs([name for name, _, _ in results])
        for tab, (name, state, charts) in zip(tabs, results):
            with tab:
                display_results(state, charts, name)
    else:
        name, state, charts = results[0]
        st.header(f"Results — {name}")
        display_results(state, charts, name)
