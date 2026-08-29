"""Deterministic cross-column consistency checks. Mines high-purity functional dependencies between related columns, ignoring dependencies that shift over time, and columns that are timestamps or near-unique on either side: a key cannot be a semantic determinant, and a timestamp is set by the ingestion process rather than implied by another field and reports the rows that contradict the dominant mapping, so that a value inconsistent with its own key (a tax code paired with the wrong tax name, a province paired with the wrong region) is surfaced as a violation the Unified agent can repair. A row is reported once however many predictors condemn it, which both keeps the consistency count equal to a row count and bounds the output at one violation per row. Backs the Consistency Validation performed by the Format & Consistency agent."""
from __future__ import annotations

import pandas as pd

from models import FormatViolation, ValidationReport
from tools.temporal_stability import is_stable

_MAX_FALLBACK_PREDICTORS = 8

_MIN_PURITY = 0.9
_MIN_GROUPS = 3
_MIN_ROWS_PER_GROUP = 2
_MAX_PREDICTOR_CARDINALITY = 0.2
_TIMESTAMP_TEXT = r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}"
_TEMPORAL_SHARE = 0.9


def cross_column_reports(
    df: pd.DataFrame,
    candidate_predictors: dict[str, list[str]],
    min_purity: float = _MIN_PURITY,
    clock: str | None = None,
) -> list[ValidationReport]:
    reports: dict[str, list[FormatViolation]] = {}
    for target, predictors in candidate_predictors.items():
        if target not in df.columns or not _usable_column(df[target]):
            continue
        for predictor in predictors:
            if predictor not in df.columns or predictor == target:
                continue
            if not _usable_column(df[predictor], role="predictor"):
                continue
            if not is_stable(df, predictor, target, clock):
                continue
            violations = _check_dependency(df, predictor, target, min_purity)
            if violations:
                reports.setdefault(target, []).extend(violations)
    return [
        ValidationReport(column_name=column, violations=_one_per_row(violations))
        for column, violations in reports.items()
    ]


def _one_per_row(violations: list[FormatViolation]) -> list[FormatViolation]:
    seen: set[int] = set()
    unique: list[FormatViolation] = []
    for violation in violations:
        if violation.row_index in seen:
            continue
        seen.add(violation.row_index)
        unique.append(violation)
    return unique


def _usable_column(series: pd.Series, role: str = "target") -> bool:
    """A timestamp is set by the ingestion process, so nothing should imply it and it is never a
    valid target. As a predictor it is legitimate - the month a file was processed determines the
    period it covers - provided it is keyed by month, since the raw instant is nearly unique."""
    if _is_temporal(series):
        return role == "predictor"
    populated = int(series.notna().sum())
    if not populated:
        return False
    return series.nunique(dropna=True) / populated <= _MAX_PREDICTOR_CARDINALITY


def period_key(series: pd.Series) -> pd.Series:
    """Collapses a timestamp to the month it belongs to, leaving anything else untouched."""
    if not _is_temporal(series):
        return series
    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    return parsed.dt.strftime("%Y-%m")


def _is_temporal(series: pd.Series) -> bool:
    """A timestamp is set by the ingestion process, never implied by another field. The dtype
    alone is not enough to recognise one: the same column read back from a CSV arrives as text,
    and would then be compared against every other column as if it were a category."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    if values.empty or not pd.api.types.is_object_dtype(values):
        return False
    return bool(values.astype(str).str.match(_TIMESTAMP_TEXT).mean() >= _TEMPORAL_SHARE)


def _check_dependency(
    df: pd.DataFrame, predictor: str, target: str, min_purity: float
) -> list[FormatViolation]:
    usable = pd.DataFrame({
        predictor: period_key(df[predictor]),
        target: df[target],
    }).dropna()
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
            kind="consistency",
            expected_pattern=(
                f"cross-column: {predictor}={row[predictor]!r} implies "
                f"{target}={expected[row[predictor]]!r}"
            ),
        )
        for index, row in deviating.iterrows()
    ]


def candidate_predictors(payload, columns: set[str], df: pd.DataFrame) -> dict[str, list[str]]:
    """Columns the LLM flagged as related, plus every low-cardinality column: the model's
    list is a hint, never the whole search space, because a dependency it forgets to mention
    would otherwise never be looked for."""
    candidates: dict[str, list[str]] = {}
    by_name = {p.column_name: p for p in payload}
    for target in columns:
        entry = by_name.get(target)
        if entry is None:
            continue
        related = [c for c in entry.related_columns if c != target and c in df.columns]
        mined = _low_cardinality_columns(df, target)
        candidates[target] = list(dict.fromkeys(related + mined))
    return candidates


def _low_cardinality_columns(df: pd.DataFrame, target: str) -> list[str]:
    target_ratio = _cardinality(df, target)
    ranked = []
    for column in df.columns:
        ratio = _cardinality(df, column)
        if column == target or ratio is None or ratio > _MAX_PREDICTOR_CARDINALITY:
            continue
        distance = abs(ratio - target_ratio) if target_ratio is not None else ratio
        ranked.append((distance, column))
    return [column for _, column in sorted(ranked)[:_MAX_FALLBACK_PREDICTORS]]


def _cardinality(df: pd.DataFrame, column: str) -> float | None:
    populated = int(df[column].notna().sum())
    return df[column].nunique(dropna=True) / populated if populated else None

def coherence_score(
    df: pd.DataFrame, column: str, exclude: set[str]
) -> tuple[float, str] | None:
    """How well a column agrees with the column that best explains it: the share of rows
    whose value matches the dominant value for their key, taken over the strongest usable
    predictor. Averaging over every predictor would drown the signal among columns that
    have no bearing on this one. Used to pick which of two duplicate columns carries the
    correct data."""
    if column not in df.columns or not _usable_column(df[column]):
        return None
    best: tuple[float, str] | None = None
    for predictor in df.columns:
        if predictor == column or predictor in exclude or not _usable_column(df[predictor], role="predictor"):
            continue
        usable = df[[predictor, column]].dropna()
        if len(usable) < _MIN_ROWS_PER_GROUP * _MIN_GROUPS:
            continue
        dominant = usable.groupby(predictor)[column].agg(lambda v: v.value_counts().idxmax())
        score = round(float((usable[column] == usable[predictor].map(dominant)).mean()), 4)
        if best is None or score > best[0]:
            best = (score, str(predictor))
    return best
