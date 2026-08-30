"""Applies the corrections that the data itself determines, before any proposal reaches the human gate. Four kinds qualify: rewriting a value expressed in an alternative but unambiguous layout, dropping representation noise from a number recorded at a known precision, restoring a value that its own key states directly - the year and month of an accounting period - and filling a gap from a mined functional dependency of near-perfect purity. The lookup only carries keys that map to a single observed value, so a body renamed halfway through the year is skipped on its own rows rather than disqualifying the whole column. Both are deductions rather than judgement calls, so withholding them behind an approval adds no safety and only leaves the dataset incomplete. Anything that requires choosing what a value ought to be stays with the Unified Remediation agent. Implements the Auto Remediation agent node. Whatever it rewrites it also re-measures: the format violations of every touched column are recomputed and the settled value corrections dropped, so the Unified agent downstream reasons about the dataset as it now stands rather than as it was profiled."""
from __future__ import annotations

import pandas as pd

from models import FormatSpec, FormatViolation, ImputationHint, Operation, ValidationReport
from state import PipelineState
from tools.change_log import diff_cells
from tools.cross_column_checks import candidate_predictors, cross_column_reports
from tools.decimal_precision import recorded_precision, rounds_cleanly
from tools.merge_reports import merge_reports
from tools.mine_functional_deps import mine_functional_deps
from tools.normalize_period_format import is_canonical
from tools.derive_from_period import derivable_columns, derive
from tools.operations import apply_operation
from tools.temporal_stability import time_column
from tools.validate_format import specs_by_column, validate_format

_AUTO_IMPUTE_PURITY = 0.99
_MISSING_PATTERNS = ("missing value", "not nullable")


def auto_remediation_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    before = state.dataset
    df = before.copy()
    applied: list[dict] = []
    rounded_precisions: dict[str, int] = {}

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
        if not _has_excess_decimals(df[column], precision):
            continue
        changed = _apply(df, Operation(kind="round_decimals", column=str(column), digits=precision))
        if changed:
            rounded_precisions[str(column)] = precision
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
    touched = {entry["column"] for entry in applied}
    specs = _realign_range_bounds(state.inferred_format_specs, rounded_precisions)
    return state.model_copy(update={
        "dataset": df,
        "inferred_format_specs": specs,
        "validation_reports": _refresh_reports(
            state.validation_reports,
            df,
            touched,
            specs_by_column(specs),
            _recheck_cross_column(state, df),
        ),
        "value_corrections": _drop_settled_corrections(state.value_corrections, df, touched),
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


def _refresh_reports(
    reports: list[ValidationReport],
    df: pd.DataFrame,
    touched: set[str],
    specs: dict[str, FormatSpec | None],
    consistency: list[ValidationReport],
) -> list[ValidationReport]:
    """Re-measures what this node rewrote, so the Unified agent downstream is handed the violations
    the dataset still carries rather than the ones it carried before remediation. Format checks are
    recomputed per rewritten column; cross-column findings are replaced wholesale, since a rule
    relates two columns and rewriting either side invalidates the finding on both."""
    refreshed: list[ValidationReport] = []
    for report in reports:
        column = report.column_name
        if column in touched and column in df.columns:
            violations = _revalidated_violations(report, df[column], specs.get(column))
        else:
            violations = [v for v in report.violations if v.kind != "consistency"]
        if violations:
            refreshed.append(report.model_copy(update={"violations": violations}))
    return merge_reports(refreshed, consistency)


def _realign_range_bounds(
    specs: dict[str, dict], rounded: dict[str, int]
) -> dict[str, dict]:
    """A range bound is read off the values themselves, float noise included, so rounding a column
    can leave its own extreme value a fraction outside the bound derived from the unrounded form.
    Rounding is monotonic, so rounding the bound to the same precision restores containment for
    every value without widening the check."""
    if not rounded:
        return specs
    realigned = dict(specs)
    for column, precision in rounded.items():
        info = realigned.get(column) or {}
        spec = info.get("final_spec") or {}
        if spec.get("type") != "range":
            continue
        realigned[column] = {**info, "final_spec": {**spec, **_rounded_bounds(spec, precision)}}
    return realigned


def _rounded_bounds(spec: dict, precision: int) -> dict:
    return {
        bound: round(float(spec[bound]), precision)
        for bound in ("min", "max")
        if spec.get(bound) is not None
    }


def _recheck_cross_column(state: PipelineState, df: pd.DataFrame) -> list[ValidationReport]:
    return cross_column_reports(
        df,
        candidate_predictors(state.payload, set(state.surviving_columns), df),
        clock=time_column(df, state.inferred_format_specs),
    )


def _revalidated_violations(
    report: ValidationReport, series: pd.Series, spec: FormatSpec | None
) -> list[FormatViolation]:
    remaining_missing = int(series.isna().sum())
    kept: list[FormatViolation] = []
    for violation in report.violations:
        if violation.expected_pattern in _MISSING_PATTERNS:
            if remaining_missing:
                kept.append(violation.model_copy(update={"value": remaining_missing}))
            continue
        if violation.kind in ("format", "consistency"):
            continue
        kept.append(violation)
    if spec is None:
        return kept
    already_reported = {violation.row_index for violation in kept if violation.row_index >= 0}
    kept.extend(
        violation
        for violation in validate_format(report.column_name, series, spec).violations
        if violation.row_index not in already_reported
    )
    return kept


def _drop_settled_corrections(
    corrections: dict[str, dict[str, str | None]], df: pd.DataFrame, touched: set[str]
) -> dict[str, dict[str, str | None]]:
    """Keeps only the corrections whose offending value survives in the column. A value this node
    already rewrote is no longer evidence of anything, and proposing its replacement downstream
    would spend the approval gate on a fix that changes nothing."""
    filtered: dict[str, dict[str, str | None]] = {}
    for column, mapping in corrections.items():
        if column not in touched or column not in df.columns:
            filtered[column] = mapping
            continue
        present = set(df[column].dropna().astype(str))
        surviving = {value: replacement for value, replacement in mapping.items() if value in present}
        if surviving:
            filtered[column] = surviving
    return filtered


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


def _has_excess_decimals(series: pd.Series, precision: int) -> bool:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    return bool((numeric != numeric.round(precision)).any())
