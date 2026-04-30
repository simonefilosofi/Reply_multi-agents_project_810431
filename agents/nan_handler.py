"""Replaces disguised NaNs in every column using the per-column placeholder lists from the payload, then flags columns whose canonical spec says is_nullable=false but where NaNs remain after replacement, surfacing them as aggregated ValidationReport entries on state.validation_reports."""
from __future__ import annotations

import pandas as pd

from models import FormatViolation, ValidationReport
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.detect_placeholders import detect_placeholders


def nan_handler_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset.copy()
    for p in state.payload:
        if p.column_name in df.columns and p.placeholders:
            df[p.column_name] = detect_placeholders(df[p.column_name], p.placeholders)

    nullability_reports = _check_nullability(df, state)
    merged = _merge_reports(state.validation_reports, nullability_reports)

    return state.model_copy(update={"dataset": df, "validation_reports": merged})


def _check_nullability(df: pd.DataFrame, state: PipelineState) -> list[ValidationReport]:
    if state.baseline is None:
        return []
    reports: list[ValidationReport] = []
    for p in state.payload:
        if not p.canonical_hint or p.column_name not in df.columns:
            continue
        spec = find_spec_by_hint(state.baseline, state.detected_domain, p.canonical_hint)
        if spec is None or spec.is_nullable:
            continue
        nan_count = int(df[p.column_name].isna().sum())
        if nan_count == 0:
            continue
        reports.append(ValidationReport(
            column_name=p.column_name,
            violations=[FormatViolation(
                column_name=p.column_name,
                row_index=-1,
                value=nan_count,
                expected_pattern="not nullable",
            )],
        ))
    return reports


def _merge_reports(existing: list[ValidationReport], new: list[ValidationReport]) -> list[ValidationReport]:
    by_col: dict[str, ValidationReport] = {r.column_name: r for r in existing}
    for n in new:
        if n.column_name in by_col:
            by_col[n.column_name].violations.extend(n.violations)
        else:
            by_col[n.column_name] = n
    return list(by_col.values())
