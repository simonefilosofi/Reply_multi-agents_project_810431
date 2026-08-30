"""Computes the deterministic data-quality metrics and the aggregate reliability score reported for each pipeline run. Metrics are captured at three points - the raw file, the dataset once disguised nulls are unmasked, and the remediated result - so that unmasking placeholders is not mistaken for a loss of completeness. Every dimension divides by the units it actually evaluated rather than by the whole grid, and compare() scores the two ends of a run over the same set of dimensions so the delta is like-for-like. Consumed by the Report Generator."""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict

import pandas as pd

from models import GlobalConventions, ValidationReport
from tools.safe_cast import dtype_satisfied
from tools.validate_column_names import is_conforming

_COMPLETENESS_PATTERNS = {"not nullable", "missing value"}
_SCHEMA_PATTERN_PREFIXES = ("naming convention", "sparse column", "duplicate-column divergence")
_CONSISTENCY_PATTERN_PREFIX = "cross-column"
_UNIQUENESS_PATTERN_PREFIX = "duplicate records"

_SPARSE_NULL_RATE = 0.9

DIMENSIONS = ("completeness", "validity", "consistency", "uniqueness", "schema_conformity")
DIMENSION_WEIGHTS: dict[str, float] = {dimension: 1.0 for dimension in DIMENSIONS}


def classify_violation(pattern) -> str:
    """Derives the kind from a message. Producers now declare `kind` directly; this remains the
    documented inverse, used to build reports by hand and to read anything written before the
    field existed."""
    text = str(pattern or "")
    if text in _COMPLETENESS_PATTERNS:
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
            counts[violation.kind] += (
                violation.affected_rows if violation.kind == "completeness" else 1
            )
    return counts


def inconsistent_rows(reports) -> int:
    return len({
        violation.row_index
        for report in reports
        for violation in report.violations
        if violation.row_index >= 0
        and violation.kind == "consistency"
    })


def checked_cells_by_column(df: pd.DataFrame, inferred_format_specs: dict) -> dict[str, int]:
    """The populated cells of every column carrying a format specification. Kept per column so
    that a comparison restricted to a subset of columns can rebuild its own denominator instead
    of borrowing the whole frame's."""
    return {
        str(column): int(df[column].notna().sum())
        for column, info in (inferred_format_specs or {}).items()
        if column in df.columns and (info or {}).get("final_spec")
    }


def format_violations_by_column(reports) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for report in reports:
        found = violation_counts([report])["format"]
        if found:
            counts[report.column_name] += found
    return dict(counts)


def inconsistent_rows_by_column(reports) -> dict[str, int]:
    rows: dict[str, set[int]] = defaultdict(set)
    for report in reports:
        for violation in report.violations:
            if violation.row_index >= 0 and violation.kind == "consistency":
                rows[report.column_name].add(violation.row_index)
    return {column: len(indices) for column, indices in rows.items()}


def structural_defects(
    df: pd.DataFrame,
    conventions: GlobalConventions | None,
    declared_dtypes: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Column-level faults that no row-level metric can see: a name that breaks the convention,
    a column empty enough to carry no information, a column still holding the wrong type, and a
    column whose values merely repeat another's. These are what makes a delivered file structurally unusable, and counting them is
    what stops the score from resting on row-level dimensions that sit near 1.0 by construction."""
    defects: dict[str, list[str]] = {}
    seen: dict[str, str] = {}
    rows = len(df)
    for column in df.columns:
        name = str(column)
        found: list[str] = []
        if not is_conforming(name, conventions):
            found.append("naming")
        if rows and float(df[column].isna().mean()) >= _SPARSE_NULL_RATE:
            found.append("sparse")
        declared = (declared_dtypes or {}).get(name)
        if declared and not dtype_satisfied(declared, str(df[column].dtype)):
            found.append("untyped")
        fingerprint = _fingerprint(df[column])
        if fingerprint in seen:
            found.append("redundant")
        else:
            seen[fingerprint] = name
        if found:
            defects[name] = found
    return defects


def compute_metrics(
    df: pd.DataFrame,
    validation_reports: list[ValidationReport] | None = None,
    conventions: GlobalConventions | None = None,
    checked_cells: dict[str, int] | None = None,
    declared_dtypes: dict[str, str] | None = None,
    duplicate_analysis: dict | None = None,
) -> dict:
    rows = int(len(df))
    cells = int(df.size)
    null_cells = int(df.isna().sum().sum())
    duplicate_rows = int(df.duplicated().sum())
    rows_in_key_conflict = _rows_in_key_conflict(duplicate_analysis)
    defects = structural_defects(df, conventions, declared_dtypes)
    metrics: dict = {
        "null_by_column": {str(c): int(df[c].isna().sum()) for c in df.columns},
        "rows": rows,
        "columns": int(len(df.columns)),
        "cells": cells,
        "null_cells": null_cells,
        "duplicate_rows": duplicate_rows,
        "rows_in_key_conflict": rows_in_key_conflict,
        "checked_cells": sum(checked_cells.values()) if checked_cells else None,
        "checked_cells_by_column": checked_cells or {},
        "completeness": _ratio(cells - null_cells, cells),
        "uniqueness": _ratio(rows - duplicate_rows - rows_in_key_conflict, rows),
        "schema_conformity": _ratio(len(df.columns) - len(defects), len(df.columns)),
        "structural_defects": defects,
        "columns_with_structural_defects": len(defects),
        "columns_badly_named": sum(1 for d in defects.values() if "naming" in d),
        "columns_sparse": sum(1 for d in defects.values() if "sparse" in d),
        "columns_redundant": sum(1 for d in defects.values() if "redundant" in d),
        "columns_untyped": sum(1 for d in defects.values() if "untyped" in d),
    }
    if validation_reports is not None:
        counts = violation_counts(validation_reports)
        inconsistent = inconsistent_rows(validation_reports)
        checked = metrics["checked_cells"]
        metrics["violations_by_kind"] = counts
        metrics["format_violations"] = counts["format"]
        metrics["format_violations_by_column"] = format_violations_by_column(validation_reports)
        metrics["inconsistent_rows"] = inconsistent
        metrics["inconsistent_rows_by_column"] = inconsistent_rows_by_column(validation_reports)
        metrics["validity"] = _ratio(checked - counts["format"], checked) if checked else None
        metrics["consistency"] = _ratio(rows - inconsistent, rows)
    return metrics


def reliability_score(metrics: dict, dimensions: tuple[str, ...] = DIMENSIONS) -> dict:
    components = {
        dimension: metrics[dimension]
        for dimension in dimensions
        if metrics.get(dimension) is not None
    }
    if not components:
        return {"components": {}, "weights": {}, "score": None}
    weights = {dimension: DIMENSION_WEIGHTS[dimension] for dimension in components}
    product = math.prod(components[d] ** weights[d] for d in components)
    return {
        "components": components,
        "weights": weights,
        "score": round(product ** (1 / sum(weights.values())), 4),
    }


def compare(before: dict, after: dict) -> dict:
    dimensions = tuple(
        dimension for dimension in DIMENSIONS
        if before.get(dimension) is not None and after.get(dimension) is not None
    )
    return {
        "dimensions": list(dimensions),
        "before": reliability_score(before, dimensions),
        "after": reliability_score(after, dimensions),
    }


def _rows_in_key_conflict(duplicate_analysis: dict | None) -> int:
    collisions = (duplicate_analysis or {}).get("key_collisions") or {}
    return max(
        (int(stats.get("rows_in_conflicting_groups", 0)) for stats in collisions.values()),
        default=0,
    )


def _fingerprint(series: pd.Series) -> str:
    hashed = pd.util.hash_pandas_object(series.astype(str), index=False)
    return hashlib.sha1(hashed.values.tobytes()).hexdigest()


def _ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(max(min(numerator / denominator, 1.0), 0.0), 4)
