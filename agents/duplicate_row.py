"""Drops exact duplicate rows as the final cleaning step."""
from __future__ import annotations

from state import PipelineState


def duplicate_row_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset.drop_duplicates()
    return state.model_copy(update={"dataset": df})
