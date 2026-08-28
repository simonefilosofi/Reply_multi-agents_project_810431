"""Executable catalogue of remediation operations. A fix is expressed as a typed operation with validated parameters rather than as generated Python, so that every action is deterministic, reviewable, replayable, and structurally incapable of inventing data. A replacement of None clears the value, which the post-fix invariants then hold to the deletion budget. Each entry maps an Operation to a pure dataframe transformation, and renders itself as a human-readable line for the report and the approval gate."""
from __future__ import annotations

import pandas as pd

from models import Operation
from tools.apply_casing import collapse_casing_variants
from tools.normalize_date_format import normalize_date_format
from tools.normalize_numeric_format import normalize_numeric_format
from tools.safe_cast import safe_cast


def apply_operations(
    df: pd.DataFrame,
    operations: list[Operation],
    imputation_hints: dict | None = None,
) -> pd.DataFrame:
    result = df.copy()
    for operation in operations:
        result = apply_operation(result, operation, imputation_hints or {})
    return result


def apply_operation(
    df: pd.DataFrame, operation: Operation, imputation_hints: dict | None = None
) -> pd.DataFrame:
    if operation.kind == "drop_duplicate_rows":
        subset = [c for c in operation.subset if c in df.columns]
        return df.drop_duplicates(subset=subset or None)

    if operation.column not in df.columns:
        return df
    if operation.kind == "drop_column":
        return df.drop(columns=[operation.column])

    df[operation.column] = _transform(df[operation.column], operation, imputation_hints or {}, df)
    return df


def describe_operation(operation: Operation) -> str:
    if operation.kind == "replace_values":
        shown = operation.mapping[:3]
        rendered = ", ".join(f"{m.value!r} -> {m.replacement!r}" for m in shown)
        suffix = "" if len(operation.mapping) <= 3 else f" (+{len(operation.mapping) - 3} more)"
        return f"replace_values on {operation.column}: {rendered}{suffix}"
    if operation.kind == "round_decimals":
        return f"round_decimals on {operation.column} to {operation.digits} digits"
    if operation.kind == "cast_dtype":
        return f"cast_dtype on {operation.column} to {operation.dtype}"
    if operation.kind == "drop_duplicate_rows":
        return f"drop_duplicate_rows on {operation.subset or 'all columns'}"
    return f"{operation.kind} on {operation.column}"


def _transform(
    series: pd.Series, operation: Operation, hints: dict, df: pd.DataFrame
) -> pd.Series:
    if operation.kind == "replace_values":
        mapping = {m.value: (m.replacement if m.replacement is not None else pd.NA) for m in operation.mapping}
        return series.replace(mapping) if mapping else series
    if operation.kind == "normalize_numeric":
        return normalize_numeric_format(series)
    if operation.kind == "normalize_date":
        return normalize_date_format(series)
    if operation.kind == "strip_whitespace":
        return series.astype("string").str.strip() if _is_text(series) else series
    if operation.kind == "collapse_casing":
        return collapse_casing_variants(series)
    if operation.kind == "round_decimals":
        numeric = pd.to_numeric(series, errors="coerce")
        return numeric.round(operation.digits).where(numeric.notna(), series)
    if operation.kind == "cast_dtype":
        cast, blocking = safe_cast(series, operation.dtype)
        return series if blocking else cast
    if operation.kind == "impute_from_lookup":
        return _impute(series, hints.get(operation.column), df)
    return series


def _impute(series: pd.Series, hint: dict | None, df: pd.DataFrame) -> pd.Series:
    if not hint:
        return series
    predictors = hint.get("predictor_columns") or []
    mapping = hint.get("mapping") or {}
    if len(predictors) != 1 or predictors[0] not in df.columns or not mapping:
        return series
    return series.fillna(df[predictors[0]].astype("string").map(mapping))


def _is_text(series: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
