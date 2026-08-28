"""Deterministic post-fix checks that no remediation may violate, evaluated on the before/after dataframes of a single FixProposal. Enforces that a fix never invents data, never splits a column into casing variants, and never changes the row count outside a declared deduplication. Consumed by the trial run of the Unified Remediation agent and by the local executor."""
from __future__ import annotations

import pandas as pd

_DEDUP_MARKERS = ("drop_duplicates", "duplicated")


def check_invariants(
    before: pd.DataFrame,
    after: pd.DataFrame,
    code: str,
    imputation_hints: dict | None = None,
) -> list[str]:
    hints = imputation_hints or {}
    failures: list[str] = []
    failures.extend(_check_row_count(before, after, code))
    for column in after.columns:
        if column not in before.columns:
            continue
        failures.extend(_check_invented_values(before[column], after[column], column, hints))
        failures.extend(_check_casing_split(before[column], after[column], column))
    return failures


def _check_row_count(before: pd.DataFrame, after: pd.DataFrame, code: str) -> list[str]:
    if len(after) == len(before):
        return []
    if any(marker in code for marker in _DEDUP_MARKERS):
        return []
    return [
        f"row count changed from {len(before)} to {len(after)} without a declared deduplication"
    ]


def _check_invented_values(
    before: pd.Series, after: pd.Series, column: str, hints: dict
) -> list[str]:
    filled = int(before.isna().sum() - after.isna().sum())
    if filled <= 0 or column in hints:
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
