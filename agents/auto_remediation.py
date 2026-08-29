"""Applies the corrections that the data itself determines, before any proposal reaches the human gate. Two kinds qualify: rewriting a value expressed in an alternative but unambiguous layout, and filling a gap from a mined functional dependency of near-perfect purity. The lookup only carries keys that map to a single observed value, so a body renamed halfway through the year is skipped on its own rows rather than disqualifying the whole column. Both are deductions rather than judgement calls, so withholding them behind an approval adds no safety and only leaves the dataset incomplete. Anything that requires choosing what a value ought to be stays with the Unified Remediation agent. Implements the Auto Remediation agent node."""
from __future__ import annotations

import pandas as pd

from models import ImputationHint, Operation, ValidationReport
from state import PipelineState
from tools.change_log import diff_cells
from tools.operations import apply_operation

_AUTO_IMPUTE_PURITY = 0.99


def auto_remediation_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    before = state.dataset
    df = before.copy()
    applied: list[dict] = []

    for column in _period_columns(state):
        rewritten = _apply(df, Operation(kind="normalize_period", column=column))
        if rewritten:
            applied.append({
                "column": column,
                "operation": "normalize_period",
                "cells_changed": rewritten,
                "rationale": "alternative period layouts rewritten to the canonical YYYYMM form",
            })

    hints = _certain_hints(state)
    hints_view = {column: hint.model_dump() for column, hint in hints.items()}
    for column, hint in hints.items():
        filled = _apply(df, Operation(kind="impute_from_lookup", column=column), hints_view)
        if filled:
            applied.append({
                "column": column,
                "operation": "impute_from_lookup",
                "cells_changed": filled,
                "predictor_columns": hint.predictor_columns,
                "purity": round(hint.purity, 4),
                "cells_still_missing": int(df[column].isna().sum()),
                "rationale": hint.rationale,
            })

    if not applied:
        return state

    changes, _ = diff_cells(before, df, "auto_remediation")
    return state.model_copy(update={
        "dataset": df,
        "validation_reports": _refresh_completeness(
            state.validation_reports, df, {entry["column"] for entry in applied}
        ),
        "change_log": state.change_log + changes,
        "auto_remediations": state.auto_remediations + applied,
    })


def _apply(df: pd.DataFrame, operation: Operation, hints: dict | None = None) -> int:
    column = operation.column
    if column not in df.columns:
        return 0
    before = df[column].copy()
    apply_operation(df, operation, hints or {})
    return int((before.astype(str) != df[column].astype(str)).sum())


def _certain_hints(state: PipelineState) -> dict[str, ImputationHint]:
    return {
        column: hint
        for column, hint in state.imputation_hints.items()
        if hint.purity >= _AUTO_IMPUTE_PURITY and column in state.dataset.columns
    }


def _period_columns(state: PipelineState) -> list[str]:
    columns = []
    for column, info in state.inferred_format_specs.items():
        spec = (info or {}).get("final_spec") or {}
        pattern = spec.get("strftime_pattern", "")
        if spec.get("type") == "date" and "%d" not in pattern and column in state.dataset.columns:
            columns.append(column)
    return columns


def _refresh_completeness(
    reports: list[ValidationReport], df: pd.DataFrame, touched: set[str]
) -> list[ValidationReport]:
    refreshed: list[ValidationReport] = []
    for report in reports:
        if report.column_name not in touched:
            refreshed.append(report)
            continue
        remaining = int(df[report.column_name].isna().sum())
        violations = [
            violation.model_copy(update={"value": remaining})
            if violation.expected_pattern in ("missing value", "not nullable")
            else violation
            for violation in report.violations
            if violation.expected_pattern not in ("missing value", "not nullable") or remaining
        ]
        if violations:
            refreshed.append(report.model_copy(update={"violations": violations}))
    return refreshed
