"""Deterministic cross-column consistency checks. Mines high-purity functional dependencies between related columns, ignoring columns that are timestamps or near-unique on either side of the dependency: a key cannot be a semantic determinant, and a timestamp is set by the ingestion process rather than implied by another field and reports the rows that contradict the dominant mapping, so that a value inconsistent with its own key (a tax code paired with the wrong tax name, a province paired with the wrong region) is surfaced as a violation the Unified agent can repair. Backs the Consistency Validation performed by the Format & Consistency agent."""
from __future__ import annotations

import pandas as pd

from models import FormatViolation, ValidationReport

_MAX_FALLBACK_PREDICTORS = 5

_MIN_PURITY = 0.9
_MIN_GROUPS = 3
_MIN_ROWS_PER_GROUP = 2
_MAX_VIOLATIONS_PER_PAIR = 200
_MAX_PREDICTOR_CARDINALITY = 0.2


def cross_column_reports(
    df: pd.DataFrame,
    candidate_predictors: dict[str, list[str]],
    min_purity: float = _MIN_PURITY,
) -> list[ValidationReport]:
    reports: dict[str, list[FormatViolation]] = {}
    for target, predictors in candidate_predictors.items():
        if target not in df.columns or not _usable_column(df[target]):
            continue
        for predictor in predictors:
            if predictor not in df.columns or predictor == target:
                continue
            if not _usable_column(df[predictor]):
                continue
            violations = _check_dependency(df, predictor, target, min_purity)
            if violations:
                reports.setdefault(target, []).extend(violations)
    return [
        ValidationReport(column_name=column, violations=violations[:_MAX_VIOLATIONS_PER_PAIR])
        for column, violations in reports.items()
    ]


def _usable_column(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return False
    populated = int(series.notna().sum())
    if not populated:
        return False
    return series.nunique(dropna=True) / populated <= _MAX_PREDICTOR_CARDINALITY


def _check_dependency(
    df: pd.DataFrame, predictor: str, target: str, min_purity: float
) -> list[FormatViolation]:
    usable = df[[predictor, target]].dropna()
    if usable.empty:
        return []

    grouped = usable.groupby(predictor)[target]
    sizes = grouped.size()
    eligible = sizes[sizes >= _MIN_ROWS_PER_GROUP].index
    if len(eligible) < _MIN_GROUPS:
        return []

    expected = grouped.agg(lambda values: values.value_counts().idxmax())
    purity = float((usable[target] == usable[predictor].map(expected)).mean())
    if purity < min_purity or purity >= 1.0:
        return []

    deviating = usable[
        usable[predictor].isin(eligible) & (usable[target] != usable[predictor].map(expected))
    ]
    return [
        FormatViolation(
            column_name=target,
            row_index=int(index),
            value=row[target],
            expected_pattern=(
                f"cross-column: {predictor}={row[predictor]!r} implies "
                f"{target}={expected[row[predictor]]!r}"
            ),
        )
        for index, row in deviating.iterrows()
    ]


def candidate_predictors(payload, columns: set[str], df: pd.DataFrame) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    by_name = {p.column_name: p for p in payload}
    for target in columns:
        entry = by_name.get(target)
        if entry is None:
            continue
        related = [c for c in entry.related_columns if c != target and c in df.columns]
        candidates[target] = related or _low_cardinality_columns(df, target)
    return candidates


def _low_cardinality_columns(df: pd.DataFrame, target: str) -> list[str]:
    ranked = []
    for column in df.columns:
        populated = int(df[column].notna().sum())
        if column == target or not populated:
            continue
        ratio = df[column].nunique(dropna=True) / populated
        if ratio <= _MAX_PREDICTOR_CARDINALITY:
            ranked.append((ratio, column))
    return [column for _, column in sorted(ranked)[:_MAX_FALLBACK_PREDICTORS]]
