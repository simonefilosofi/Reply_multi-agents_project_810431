"""Validates column values against baseline format patterns; flags violations."""
from __future__ import annotations

from models import ValidationReport
from state import PipelineState
from tools.normalize_date_format import normalize_date_format
from tools.normalize_entity_format import normalize_entity_format
from tools.validate_format import validate_format


def format_consistency_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    reports: list[ValidationReport] = []
    for col in state.surviving_columns:
        series = state.dataset[col]
        report = validate_format(col, series, state.baseline)
        reports.append(report)
        # TODO: call LLM for ambiguous violations (prompts/format_consistency.md)

    return state.model_copy(update={"validation_reports": reports})
