"""Produces a ColumnPayload for every column via LLM, then validates dtype programmatically."""
from __future__ import annotations

from models import ColumnPayload
from state import PipelineState
from tools.infer_and_validate_dtype import infer_and_validate_dtype


def semantic_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    payload: list[ColumnPayload] = []
    for col in state.dataset.columns:
        # TODO: call LLM with prompts/semantic.md to fill all payload fields
        dtype = infer_and_validate_dtype(state.dataset[col], llm_suggestion=None)
        payload.append(ColumnPayload(
            column_name=col,
            domain=state.detected_domain,
            dtype=dtype,
            sample=state.dataset[col].dropna().head(5).tolist(),
        ))

    return state.model_copy(update={"payload": payload})
