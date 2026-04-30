"""Generates a normalized column name and short description for each surviving column."""
from __future__ import annotations

from models import ColumnClassification
from state import PipelineState


def classification_node(state: PipelineState) -> PipelineState:
    classifications: list[ColumnClassification] = []
    for col in state.surviving_columns:
        # TODO: call LLM with prompts/classification.md
        classifications.append(ColumnClassification(
            column_name=col,
            normalized_name=col.lower().replace(" ", "_"),
            description="",
        ))
    return state.model_copy(update={"classifications": classifications})
