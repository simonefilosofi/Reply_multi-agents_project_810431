"""Replaces disguised NaNs in every column using the per-column placeholder lists from the payload, then enforces the dtype proposed by the Semantic agent without losing data: a column is cast only when every non-null value survives, and blocking values are reported as violations instead of being coerced away. Finally flags columns whose canonical spec says is_nullable=false but where NaNs remain, surfacing everything as ValidationReport entries on state.validation_reports. Records the "detected" quality snapshot, the true state of the dataset once disguised nulls are unmasked."""
from __future__ import annotations

import pandas as pd

from models import FormatViolation, ValidationReport
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.detect_placeholders import detect_placeholders
from tools.reliability_score import compute_metrics
from tools.safe_cast import safe_cast


def nan_handler_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset.copy()
    for p in state.payload:
        if p.column_name in df.columns and p.placeholders:
            df[p.column_name] = detect_placeholders(df[p.column_name], p.placeholders)

    df, coercion_reports = _enforce_dtypes(df, state)
    nullability_reports = _check_nullability(df, state)
    merged = _merge_reports(state.validation_reports, coercion_reports + nullability_reports)

    snapshots = {
        **state.quality_snapshots,
        "detected": compute_metrics(df, conventions=_conventions(state)),
    }
    return state.model_copy(update={
        "dataset": df,
        "validation_reports": merged,
        "quality_snapshots": snapshots,
    })


def _conventions(state: PipelineState):
    return state.baseline.global_conventions if state.baseline else None


def _enforce_dtypes(df: pd.DataFrame, state: PipelineState) -> tuple[pd.DataFrame, list[ValidationReport]]:
    reports: list[ValidationReport] = []
    for p in state.payload:
        if p.column_name not in df.columns or not p.dtype:
            continue
        if p.dtype == str(df[p.column_name].dtype):
            continue
        cast, blocking = safe_cast(df[p.column_name], p.dtype)
        if not blocking:
            df[p.column_name] = cast
            continue
        reports.append(ValidationReport(
            column_name=p.column_name,
            violations=[FormatViolation(
                column_name=p.column_name,
                row_index=i,
                value=df[p.column_name].loc[i],
                expected_pattern=f"not coercible to {p.dtype}",
            ) for i in blocking],
        ))
    return df, reports


def _check_nullability(df: pd.DataFrame, state: PipelineState) -> list[ValidationReport]:
    if state.baseline is None:
        return []
    reports: list[ValidationReport] = []
    for p in state.payload:
        if not p.canonical_hint or p.canonical_hint == "NaN" or p.column_name not in df.columns:
            continue
        spec = find_spec_by_hint(state.baseline, p.canonical_hint)
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
