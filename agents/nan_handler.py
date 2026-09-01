"""Replaces disguised NaNs using the per-column placeholder lists from the payload, refusing any list that matches most of a column because at that scale it is describing the column's own vocabulary rather than the gaps in it, then enforces the dtype the Semantic agent proposed without losing data: a column is cast only when every non-null value survives, and blocking values are reported as violations rather than coerced away. Flags columns whose canonical spec forbids nulls but still holds them. Every value cleared and every type enforced is appended to the audit trail. Records the detected quality snapshot and the full completeness analysis - per-column and dataset-wide fill rates, missing values per row, and sparse columns - measured once disguised nulls are unmasked."""
from __future__ import annotations

import pandas as pd

from models import FormatViolation, ValidationReport
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.change_log import diff_values_only
from tools.completeness import completeness_report
from tools.merge_reports import merge_reports
from tools.detect_placeholders import detect_placeholders
from tools.reliability_score import compute_metrics
from tools.safe_cast import safe_cast

_MAX_PLACEHOLDER_SHARE = 0.3


def nan_handler_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset.copy()
    df, rejected_reports = _unmask_placeholders(df, state)

    placeholder_changes = diff_values_only(state.dataset, df, "nan_handler:placeholders")
    before_cast = df.copy()
    df, coercion_reports = _enforce_dtypes(df, state)
    cast_changes = diff_values_only(before_cast, df, "nan_handler")
    nullability_reports = _check_nullability(df, state)
    completeness = completeness_report(df)
    sparse_reports = _sparse_reports(completeness)
    merged = merge_reports(
        state.validation_reports,
        coercion_reports + nullability_reports + sparse_reports + rejected_reports,
    )

    snapshots = {
        **state.quality_snapshots,
        "detected": compute_metrics(df, conventions=_conventions(state)),
    }
    return state.model_copy(update={
        "dataset": df,
        "validation_reports": merged,
        "quality_snapshots": snapshots,
        "completeness": completeness,
        "change_log": state.change_log + placeholder_changes + cast_changes,
    })


def _unmask_placeholders(
    df: pd.DataFrame, state: PipelineState
) -> tuple[pd.DataFrame, list[ValidationReport]]:
    """Clears the placeholder tokens the Semantic agent listed, per column, unless doing so would
    empty the column. A list that matches most of a column is describing the column's own
    vocabulary rather than the gaps in it - a canonical enum stated in different words makes every
    value a spec violation - and applying it destroys the data it was meant to clean. The column
    is left as it stands and the rejection is reported so the gate can see it."""
    reports: list[ValidationReport] = []
    for p in state.payload:
        if p.column_name not in df.columns or not p.placeholders:
            continue
        series = df[p.column_name]
        cleared = detect_placeholders(series, p.placeholders)
        populated = int(series.notna().sum())
        removed = populated - int(cleared.notna().sum())
        if populated and removed / populated > _MAX_PLACEHOLDER_SHARE:
            reports.append(_rejected_placeholders_report(p.column_name, removed, populated))
            continue
        df[p.column_name] = cleared
    return df, reports


def _rejected_placeholders_report(column: str, removed: int, populated: int) -> ValidationReport:
    share = removed / populated
    return ValidationReport(
        column_name=column,
        violations=[FormatViolation(
            column_name=column,
            row_index=-1,
            value=removed,
            expected_pattern=(
                f"placeholder list rejected: it matches {share:.0%} of the populated values, "
                f"so it describes the column's vocabulary rather than its gaps"
            ),
            kind="schema",
            affected_rows=removed,
        )],
        detected_total=removed,
    )


def _sparse_reports(completeness: dict) -> list[ValidationReport]:
    return [
        ValidationReport(
            column_name=entry["column"],
            violations=[FormatViolation(
                column_name=entry["column"],
                row_index=-1,
                value=entry["nulls"],
                expected_pattern=f"sparse column: {entry['null_rate']:.1%} null",
                kind="schema",
                affected_rows=entry["nulls"],
            )],
        )
        for entry in completeness["sparse_columns"]
    ]


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
                kind="format",
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
                kind="completeness",
                affected_rows=nan_count,
            )],
        ))
    return reports

