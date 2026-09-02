"""Deterministic post-fix checks that no remediation may violate, evaluated on the before/after dataframes of a single FixProposal. Enforces that a fix never invents data, never fills a column too sparse to speak for itself, never deletes more than a small fraction of a column beyond its declared placeholders, never splits a column into casing variants, and never changes the row count outside a declared deduplication. Consumed by the trial run of the Unified Remediation agent and by the local executor."""
from __future__ import annotations

import pandas as pd

_MAX_DELETION_RATIO = 0.02
_MAX_FILLABLE_MISSING_RATE = 0.5


def check_invariants(
    before: pd.DataFrame,
    after: pd.DataFrame,
    proposal,
    imputation_hints: dict | None = None,
    removable_by_column: dict[str, set] | None = None,
) -> list[str]:
    hints = imputation_hints or {}
    removable = removable_by_column or {}
    failures: list[str] = []
    failures.extend(_check_row_count(before, after, proposal))
    for column in after.columns:
        if column not in before.columns:
            continue
        failures.extend(_check_invented_values(before[column], after[column], column, hints))
        failures.extend(_check_deleted_values(before[column], after[column], column, removable))
        failures.extend(_check_casing_split(before[column], after[column], column))
    return failures


def removable_values(payload, validation_reports=None) -> dict[str, set]:
    return {
        column.column_name: {str(value) for value in column.placeholders}
        for column in payload
    }


def _check_deleted_values(
    before: pd.Series, after: pd.Series, column: str, removable: dict[str, set]
) -> list[str]:
    erased = before.notna() & after.isna()
    if not erased.any():
        return []
    allowed = removable.get(column, set())
    unexpected = erased & ~before.astype(str).isin(allowed)
    deleted = int(unexpected.sum())
    populated = int(before.notna().sum())
    if not deleted or not populated:
        return []
    if deleted / populated <= _MAX_DELETION_RATIO:
        return []
    examples = sorted({str(value) for value in before[unexpected].unique()})[:3]
    return [
        f"{column}: {deleted} values ({deleted / populated:.1%} of the column) were deleted "
        f"without being declared placeholders, for example {examples}. Correct them instead "
        f"of discarding them, or declare them as placeholders."
    ]


def _check_row_count(before: pd.DataFrame, after: pd.DataFrame, proposal) -> list[str]:
    if len(after) == len(before):
        return []
    if any(operation.kind == "drop_duplicate_rows" for operation in proposal.operations):
        return []
    return [
        f"row count changed from {len(before)} to {len(after)} without a declared deduplication"
    ]


def _check_invented_values(
    before: pd.Series, after: pd.Series, column: str, hints: dict
) -> list[str]:
    filled = int(before.isna().sum() - after.isna().sum())
    if filled <= 0:
        return []
    missing_rate = float(before.isna().mean())
    if missing_rate > _MAX_FILLABLE_MISSING_RATE:
        return [
            f"{column}: {filled} missing values were filled, but the column was "
            f"{missing_rate:.1%} empty before the fix. A column this sparse can only be flagged "
            f"or dropped, because what little it holds cannot speak for what it does not."
        ]
    if column in hints:
        return []
    return [
        f"{column}: {filled} missing values were filled without an imputation hint"
    ]


def _check_casing_split(before: pd.Series, after: pd.Series, column: str) -> list[str]:
    if _casing_split(after) <= _casing_split(before):
        return []
    return [
        f"{column}: fix introduced values differing only by casing or surrounding whitespace"
    ]


def _casing_split(series: pd.Series) -> int:
    values = series.dropna()
    if values.empty or not pd.api.types.is_string_dtype(values.astype("string")):
        return 0
    text = values.astype("string")
    return int(text.nunique() - text.str.strip().str.casefold().nunique())
