"""Applies the corrections that the data itself determines, before any proposal reaches the human gate. Four kinds qualify: rewriting a value expressed in an alternative but unambiguous layout, dropping representation noise from a number recorded at a known precision, restoring a value that its own key states directly - the year and month of an accounting period - and filling a gap from a mined functional dependency of near-perfect purity. The lookup only carries keys that map to a single observed value, so a body renamed halfway through the year is skipped on its own rows rather than disqualifying the whole column. Both are deductions rather than judgement calls, so withholding them behind an approval adds no safety and only leaves the dataset incomplete. Anything that requires choosing what a value ought to be stays with the Unified Remediation agent. Implements the Auto Remediation agent node."""
from __future__ import annotations

import pandas as pd

from models import ImputationHint, Operation, ValidationReport
from state import PipelineState
from tools.change_log import diff_cells
from tools.decimal_precision import recorded_precision, rounds_cleanly
from tools.mine_functional_deps import mine_functional_deps
from tools.normalize_period_format import is_canonical
from tools.derive_from_period import derivable_columns, derive
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

    for period in _period_columns(state):
        for column, part in derivable_columns(df, period).items():
            corrected = derive(df, period, column, part)
            changed = int((df[column].astype(str) != corrected.astype(str)).sum())
            if not changed:
                continue
            df[column] = corrected
            applied.append({
                "column": column,
                "operation": f"derive_{part}_from_period",
                "cells_changed": changed,
                "rationale": (
                    f"{column} holds the {part} of {period}, which states it directly; "
                    f"rows contradicting their own period were corrected"
                ),
            })

    for column in df.columns:
        precision = recorded_precision(df[column])
        if precision is None or not rounds_cleanly(df[column], precision):
            continue
        changed = _apply(df, Operation(kind="round_decimals", column=str(column), digits=precision))
        if changed:
            applied.append({
                "column": str(column),
                "operation": "round_decimals",
                "cells_changed": changed,
                "rationale": (
                    f"the column is recorded at {precision} decimals; the extra digits are "
                    f"floating-point noise and rounding leaves the totals unchanged"
                ),
            })

    for period in _period_columns(state):
        filled = _complete_period(df, period)
        if filled:
            applied.append({
                "column": period,
                "operation": "complete_period_from_dependency",
                "cells_changed": filled,
                "rationale": (
                    f"values naming only a year were completed from a column that determines "
                    f"{period} exactly"
                ),
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


def _complete_period(df: pd.DataFrame, period: str) -> int:
    """A value like 'Rata 2024' states the year and withholds the month, so normalisation cannot
    touch it. Another column may still determine it exactly - a monthly run states the period it
    covers - in which case the value is derived rather than guessed."""
    incomplete = ~is_canonical(df[period]) & df[period].notna()
    if not incomplete.any():
        return 0

    probe = df.copy()
    probe[period] = df[period].where(~incomplete)
    candidates = [c for c in df.columns if c != period]
    hints = mine_functional_deps(probe, [period], {period: candidates})
    hint = hints.get(period)
    if hint is None or hint.purity < _AUTO_IMPUTE_PURITY:
        return 0

    completed = apply_operation(
        probe, Operation(kind="impute_from_lookup", column=period), {period: hint.model_dump()}
    )
    recovered = incomplete & completed[period].notna()
    if not recovered.any():
        return 0
    df[period] = df[period].where(~recovered, completed[period])
    return int(recovered.sum())
