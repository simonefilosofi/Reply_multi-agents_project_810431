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

from state.pipeline_state import PipelineState
from agents.ingestion_agent import IngestionAgent
from agents.profiler_agent import ProfilerAgent
from agents.schema_agent import SchemaAgent
from agents.completeness_agent import CompletenessAgent
from agents.duplicate_agent import DuplicateAgent
from agents.anomaly_agent import AnomalyAgent
from agents.consistency_agent import ConsistencyAgent
from agents.synthesis_agent import SynthesisAgent
from agents.remediation_agent import RemediationAgent
from agents.report_agent import ReportAgent

load_dotenv()

st.set_page_config(page_title="Data Quality Pipeline", layout="wide")
st.title("Multi-Agent Data Quality Pipeline")

uploaded_files = st.file_uploader(
    "Upload one or more datasets",
    type=["csv", "json", "xlsx", "xls", "parquet"],
    accept_multiple_files=True,
)


def run_pipeline(file_obj):
    suffix = "." + file_obj.name.rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_obj.read())
        tmp_path = tmp.name

    state = PipelineState(source_path=tmp_path)

    with st.spinner(f"[{file_obj.name}] Loading dataset..."):
        IngestionAgent(state).run()

    with st.spinner(f"[{file_obj.name}] Profiling dataset..."):
        ProfilerAgent(state).run()

    with st.spinner(f"[{file_obj.name}] Running Layer 1 analysis..."):
        SchemaAgent(state).run()
        CompletenessAgent(state).run()
        DuplicateAgent(state).run()
        AnomalyAgent(state).run()
        ConsistencyAgent(state).run()

    with st.spinner(f"[{file_obj.name}] Synthesizing results..."):
        SynthesisAgent(state).run()

    with st.spinner(f"[{file_obj.name}] Applying remediations..."):
        RemediationAgent(state).run()

    with st.spinner(f"[{file_obj.name}] Generating report..."):
        ReportAgent(state).run()

    os.unlink(tmp_path)

    chart_images = {}
    for path in state.final_report.get("visualizations", []):
        if path and os.path.exists(path):
            with open(path, "rb") as img_file:
                chart_images[os.path.basename(path)] = img_file.read()

    return state, chart_images


def display_results(state, chart_images, dataset_name):
    st.header("Reliability Score")
    before = state.reliability_score_before
    after = state.reliability_score_after
    delta = after - before

    col1, col2, col3 = st.columns(3)
    col1.metric("Before Remediation", f"{before}/100")
    col2.metric("After Remediation", f"{after}/100", delta=f"{delta:+.1f}")
    col3.metric("Improvement", f"{delta:+.1f} points")

    st.header("Dataset Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Rows", state.ingestion_meta.get("rows", "-"))
    col2.metric("Columns", state.ingestion_meta.get("columns", "-"))
    col3.metric("Format", state.source_format.upper())

    st.dataframe(state.df_raw.head(10), use_container_width=True)

    st.header("Dataset Profile")
    fp = state.dataset_fingerprint
    col1, col2 = st.columns(2)
    col1.markdown(f"**Domain:** {fp.get('domain', '-')}")
    col1.markdown(f"**Language:** {fp.get('language', '-')}")
    col2.markdown(
        f"**ID columns:** {', '.join(fp.get('id_columns', [])) or '-'}"
    )
    col2.markdown(
        f"**Date columns:** {', '.join(fp.get('date_columns', [])) or '-'}"
    )

    st.header("Executive Summary")
    st.info(
        state.final_report.get("executive_summary", state.synthesis_summary)
    )

    issues = state.prioritized_issues
    high = sum(1 for i in issues if i["severity"] == "high")
    medium = sum(1 for i in issues if i["severity"] == "medium")
    low = sum(1 for i in issues if i["severity"] == "low")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Issues", len(issues))
    col2.metric("High", high)
    col3.metric("Medium", medium)
    col4.metric("Low", low)

    st.subheader("Prioritized Issues")
    if issues:
        st.dataframe(issues, use_container_width=True)

    st.header("Remediation Results")
    fix_log = state.fix_log
    auto_fixed = [f for f in fix_log if f["action"] == "auto_fixed"]
    flagged = [f for f in fix_log if f["action"] == "flagged_for_review"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Total Actions", len(fix_log))
    col2.metric("Auto-Fixed", len(auto_fixed))
    col3.metric("Flagged for Review", len(flagged))

    if auto_fixed:
        st.subheader("Auto-Fixed Issues")
        st.dataframe(
            pd.DataFrame(auto_fixed)[
                ["issue_type", "column", "description", "rows_affected"]
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

    st.header("Visualizations")
    chart_order = [
        ("issue_severity_distribution.png", "Issue Severity Distribution"),
        ("issues_by_agent.png", "Issues by Agent"),
        ("completeness_heatmap.png", "Completeness Heatmap"),
        ("reliability_before_after.png", "Reliability Before vs After"),
    ]
    col1, col2 = st.columns(2)
    for idx, (filename, caption) in enumerate(chart_order):
        target = col1 if idx % 2 == 0 else col2
        if filename in chart_images:
            target.image(
                chart_images[filename],
                caption=caption,
                use_container_width=True,
            )

    st.header("Issues by Agent")
    reports = {
        "Schema": (state.schema_report, state.schema_summary),
        "Completeness": (
            state.completeness_report, state.completeness_summary,
        ),
        "Duplicates": (state.duplicate_report, state.duplicate_summary),
        "Anomalies": (state.anomaly_report, state.anomaly_summary),
        "Consistency": (
            state.consistency_report, state.consistency_summary,
        ),
    }
    for name, (report, summary) in reports.items():
        count = report.get("total_issues", 0)
        with st.expander(f"{name} -- {count} issue(s)"):
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

    with st.expander("Agent Communication Log"):
        if state.agent_log:
            st.dataframe(
                pd.DataFrame(state.agent_log), use_container_width=True,
            )
        else:
            st.info("No agent log entries.")

    st.header("Export")
    report_json = _serialize_report(state.final_report)
    st.download_button(
        label="Download Report (JSON)",
        data=report_json,
        file_name=f"data_quality_report_{dataset_name}.json",
        mime="application/json",
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


if uploaded_files:
    if st.button("Run Analysis"):
        results = []
        for file_obj in uploaded_files:
            state, chart_images = run_pipeline(file_obj)
            results.append((file_obj.name, state, chart_images))
        st.session_state["pipeline_results"] = results

if "pipeline_results" in st.session_state:
    results = st.session_state["pipeline_results"]

    if len(results) > 1:
        st.header("Multi-Dataset Comparison")
        cols = st.columns(len(results))
        for idx, (name, state, _) in enumerate(results):
            with cols[idx]:
                st.subheader(name)
                before = state.reliability_score_before
                after = state.reliability_score_after
                st.metric("Before", f"{before}/100")
                st.metric(
                    "After", f"{after}/100",
                    delta=f"{after - before:+.1f}",
                )
                st.metric("Issues Found", len(state.prioritized_issues))
                st.metric("Fixes Applied", len(state.fix_log))

        tabs = st.tabs([name for name, _, _ in results])
        for tab, (name, state, charts) in zip(tabs, results):
            with tab:
                display_results(state, charts, name)
    else:
        name, state, charts = results[0]
        display_results(state, charts, name)
