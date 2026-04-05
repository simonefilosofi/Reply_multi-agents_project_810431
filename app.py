import os
import tempfile
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

load_dotenv()

st.set_page_config(page_title="Data Quality Pipeline", layout="wide")
st.title("Multi-Agent Data Quality Pipeline")

uploaded = st.file_uploader("Upload a dataset", type=["csv", "json", "xlsx", "xls", "parquet"])

if uploaded:
    # Save uploaded file to a temp path so agents can read it
    suffix = "." + uploaded.name.rsplit(".", 1)[-1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    if st.button("Run Analysis"):
        state = PipelineState(source_path=tmp_path)

        with st.spinner("Loading dataset..."):
            IngestionAgent(state).run()

        with st.spinner("Profiling dataset..."):
            ProfilerAgent(state).run()

        with st.spinner("Running analysis..."):
            SchemaAgent(state).run()
            CompletenessAgent(state).run()
            DuplicateAgent(state).run()
            AnomalyAgent(state).run()
            ConsistencyAgent(state).run()

        os.unlink(tmp_path)

        # --- Dataset overview ---
        st.header("Dataset Overview")
        col1, col2, col3 = st.columns(3)
        col1.metric("Rows", state.ingestion_meta["rows"])
        col2.metric("Columns", state.ingestion_meta["columns"])
        col3.metric("Format", state.source_format.upper())

        st.dataframe(state.df_raw.head(10), use_container_width=True)

        # --- Fingerprint ---
        st.header("Dataset Profile")
        fp = state.dataset_fingerprint
        col1, col2 = st.columns(2)
        col1.markdown(f"**Domain:** {fp.get('domain', '-')}")
        col1.markdown(f"**Language:** {fp.get('language', '-')}")
        col2.markdown(f"**ID columns:** {', '.join(fp.get('id_columns', [])) or '-'}")
        col2.markdown(f"**Date columns:** {', '.join(fp.get('date_columns', [])) or '-'}")

        # --- Issues ---
        st.header("Quality Issues Found")

        reports = {
            "Schema": (state.schema_report, state.schema_summary),
            "Completeness": (state.completeness_report, state.completeness_summary),
            "Duplicates": (state.duplicate_report, state.duplicate_summary),
            "Anomalies": (state.anomaly_report, state.anomaly_summary),
            "Consistency": (state.consistency_report, state.consistency_summary),
        }

        for name, (report, summary) in reports.items():
            count = report.get("total_issues", 0)
            with st.expander(f"{name} — {count} issue(s)"):
                if summary:
                    st.info(summary)
                issues = report.get("issues", [])
                if issues:
                    st.table(issues)
                else:
                    st.success("No issues found.")
