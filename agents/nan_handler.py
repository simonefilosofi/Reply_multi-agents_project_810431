"""Replaces disguised NaNs using payload placeholder lists, then imputes or drops."""
from __future__ import annotations

from state import PipelineState
from tools.detect_placeholders import detect_placeholders


def nan_handler_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset.copy()
    payload_map = {p.column_name: p for p in state.payload}

    for col in state.surviving_columns:
        if col in payload_map and col in df.columns:
            df[col] = detect_placeholders(df[col], payload_map[col].placeholders)

    return state.model_copy(update={"dataset": df})
