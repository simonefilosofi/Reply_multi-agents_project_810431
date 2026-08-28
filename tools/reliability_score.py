"""Computes the deterministic data-quality metrics and the aggregate reliability score reported for each pipeline run. Metrics are captured at three points - the raw file, the dataset once disguised nulls are unmasked, and the remediated result - so that unmasking placeholders is not mistaken for a loss of completeness. Consumed by the Report Generator."""
from __future__ import annotations

import pandas as pd

from models import GlobalConventions, ValidationReport
from tools.validate_column_names import is_conforming

_COMPLETENESS_PATTERNS = {"not nullable", "missing value"}
_SCHEMA_PATTERN_PREFIXES = ("naming convention", "sparse column", "duplicate-column divergence")
_CONSISTENCY_PATTERN_PREFIX = "cross-column"
_UNIQUENESS_PATTERN_PREFIX = "duplicate records"


def classify_violation(pattern) -> str:
    text = str(pattern or "")
    if pattern in _COMPLETENESS_PATTERNS:
        return "completeness"
    if text.startswith(_SCHEMA_PATTERN_PREFIXES):
        return "schema"
    if text.startswith(_CONSISTENCY_PATTERN_PREFIX):
        return "consistency"
    if text.startswith(_UNIQUENESS_PATTERN_PREFIX):
        return "uniqueness"
    return "format"


def violation_counts(reports) -> dict[str, int]:
    counts = {"format": 0, "completeness": 0, "schema": 0, "consistency": 0, "uniqueness": 0}
    for report in reports:
        for violation in report.violations:
            kind = classify_violation(violation.expected_pattern)
            if kind == "completeness":
                counts[kind] += int(violation.value) if str(violation.value).isdigit() else 1
            else:
                counts[kind] += 1
    return counts


def compute_metrics(
    df: pd.DataFrame,
    validation_reports: list[ValidationReport] | None = None,
    conventions: GlobalConventions | None = None,
    typed_columns: int | None = None,
) -> dict:
    cells = int(df.size)
    rows = int(len(df))
    metrics: dict = {
        "null_by_column": {str(c): int(df[c].isna().sum()) for c in df.columns},
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "null_cells": int(df.isna().sum().sum()),
        "duplicate_rows": int(df.duplicated().sum()),
        "completeness": _ratio(cells - int(df.isna().sum().sum()), cells),
        "uniqueness": _ratio(len(df) - int(df.duplicated().sum()), len(df)),
        "schema_conformity": _schema_conformity(df, conventions, typed_columns),
    }
    if validation_reports is not None:
        counts = violation_counts(validation_reports)
        metrics["violations_by_kind"] = counts
        metrics["format_violations"] = counts["format"]
        metrics["validity"] = _ratio(max(cells - counts["format"], 0), cells)
        if counts["consistency"]:
            metrics["consistency"] = _ratio(max(rows - counts["consistency"], 0), rows)
    return metrics


def reliability_score(metrics: dict) -> dict:
    components = {
        key: metrics[key]
        for key in ("completeness", "validity", "consistency", "uniqueness", "schema_conformity")
        if metrics.get(key) is not None
    }
    if not components:
        return {"components": {}, "score": None}
    return {
        "components": components,
        "score": round(sum(components.values()) / len(components), 4),
    }


def _format_violation_count(reports: list[ValidationReport]) -> int:
    return violation_counts(reports)["format"]


def _schema_conformity(
    df: pd.DataFrame, conventions: GlobalConventions | None, typed_columns: int | None
) -> float | None:
    if df.columns.empty:
        return None
    conforming = sum(1 for column in df.columns if is_conforming(str(column), conventions))
    if typed_columns is None:
        return _ratio(conforming, len(df.columns))
    return _ratio(conforming + typed_columns, len(df.columns) * 2)


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(max(min(numerator / denominator, 1.0), 0.0), 4)
