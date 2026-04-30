"""Minimal Streamlit harness to manually exercise the Profiler, Semantic, NaN-Handler, and Duplicate-Column agents on an uploaded CSV."""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import pandas as pd
import streamlit as st

from agents.duplicate_column import duplicate_column_node
from agents.nan_handler import nan_handler_node
from agents.profiler import profiler_node
from agents.semantic import semantic_node
from state import PipelineState

st.set_page_config(page_title="NoiPA DQ — pipeline test", layout="wide")
st.title("NoiPA DQ — Profiler, Semantic, NaN, Duplicate-Column")

uploaded = st.file_uploader("Upload a CSV", type=["csv"])
if uploaded is None:
    st.stop()

df = pd.read_csv(uploaded)
st.subheader("Input preview")
st.caption(f"{df.shape[0]} rows x {df.shape[1]} columns")
st.dataframe(df.head(20))

if not st.button("Run pipeline"):
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

nan_before = state.dataset.isna().sum().to_dict()
with st.spinner("NaN handler..."):
    state = nan_handler_node(state)
nan_after = state.dataset.isna().sum().to_dict()
st.subheader("NaN handler — disguised NaNs replaced")
st.json({
    col: {"before": int(nan_before[col]), "after": int(nan_after[col])}
    for col in nan_before
    if nan_after[col] != nan_before[col]
} or {"info": "no disguised NaNs were detected"})

cols_before = list(state.dataset.columns)
nan_pre_dup = state.dataset.isna().sum().to_dict()
with st.spinner("Duplicate Column..."):
    state = duplicate_column_node(state)
dropped = [c for c in cols_before if c not in state.surviving_columns]
nan_post_dup = state.dataset.isna().sum().to_dict()
filled = {
    c: int(nan_pre_dup[c] - nan_post_dup[c])
    for c in state.surviving_columns
    if nan_pre_dup.get(c, 0) > nan_post_dup.get(c, 0)
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
