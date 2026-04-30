"""Minimal Streamlit harness to manually exercise the Profiler and Semantic agents on an uploaded CSV."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
import streamlit as st

from agents.profiler import profiler_node
from agents.semantic import semantic_node
from state import PipelineState

st.set_page_config(page_title="NoiPA DQ — Profiler/Semantic", layout="wide")
st.title("NoiPA DQ — Profiler & Semantic")

uploaded = st.file_uploader("Upload a CSV", type=["csv"])
if uploaded is None:
    st.stop()

df = pd.read_csv(uploaded)
st.subheader("Input preview")
st.dataframe(df.head(20))

if not st.button("Run Profiler + Semantic"):
    st.stop()

state = PipelineState(dataset=df, dataset_path=uploaded.name)

with st.spinner("Profiler..."):
    state = profiler_node(state)

st.subheader("Profiler output")
st.json({"detected_domain": state.detected_domain, "detected_language": state.detected_language})

with st.spinner("Semantic..."):
    state = semantic_node(state)

st.subheader("Semantic payload")
st.json([p.model_dump() for p in state.payload])
