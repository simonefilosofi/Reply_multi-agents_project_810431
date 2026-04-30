"""Replaces disguised NaNs in every column using the per-column placeholder lists from the payload."""
from __future__ import annotations

from state import PipelineState
from tools.detect_placeholders import detect_placeholders


def nan_handler_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset.copy()
    for p in state.payload:
        if p.column_name in df.columns and p.placeholders:
            df[p.column_name] = detect_placeholders(df[p.column_name], p.placeholders)

    return state.model_copy(update={"dataset": df})
