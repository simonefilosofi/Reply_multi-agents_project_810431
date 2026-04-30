"""Detects duplicate columns by hash and elects canonical names via LLM."""
from __future__ import annotations

from collections import defaultdict

from state import PipelineState
from tools.hash_column_values import hash_column_values


def duplicate_column_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    hash_to_cols: dict[str, list[str]] = defaultdict(list)
    for col in state.dataset.columns:
        h = hash_column_values(state.dataset[col])
        hash_to_cols[h].append(col)

    surviving: list[str] = []
    for cols in hash_to_cols.values():
        if len(cols) == 1:
            surviving.append(cols[0])
        else:
            # TODO: call LLM with prompts/duplicate_column.md to pick canonical name
            surviving.append(cols[0])

    return state.model_copy(update={"surviving_columns": surviving})
