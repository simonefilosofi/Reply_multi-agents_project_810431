"""Executable catalogue of remediation operations. A fix is a typed operation with validated parameters rather than generated Python, so every action is deterministic, reviewable and unable to invent data; a replacement of None clears the value, which the post-fix invariants hold to the deletion budget. Lookup keys are built as the miner built them, so a timestamp predictor is matched by month rather than by instant. Each entry renders as a readable line and as the equivalent pandas expression - documentation for every entry but apply_generated_function, whose rendered source is the code that actually runs, reaches the approval gate verbatim, and is re-read immediately before every execution."""
from __future__ import annotations

import pandas as pd

from models import Operation

_RENDERED_MAPPINGS = 4
from tools.apply_casing import collapse_casing_variants
from tools.generated_function import apply_to_series
from tools.cross_column_checks import period_key
from tools.normalize_date_format import normalize_date_format
from tools.normalize_numeric_format import normalize_numeric_format
from tools.normalize_period_format import normalize_period_format
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
    if operation.kind == "rename_column":
        if not operation.new_name or operation.new_name in df.columns:
            return df
        return df.rename(columns={operation.column: operation.new_name})

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
    if operation.kind == "apply_generated_function":
        return f"apply_generated_function on {operation.column}:\n{operation.source}"
    if operation.kind == "rename_column":
        return f"rename_column {operation.column} to {operation.new_name}"
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
    if operation.kind == "normalize_period":
        return normalize_period_format(series)
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
    if operation.kind == "apply_generated_function":
        return apply_to_series(series, operation.source)
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
    keys = period_key(df[predictors[0]]).astype("string")
    return series.fillna(keys.map(mapping))


def _is_text(series: pd.Series) -> bool:
    return pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)


def operations_as_python(operations: list[Operation]) -> str:
    return "\n".join(_as_python(operation) for operation in operations)


def _as_python(operation: Operation) -> str:
    column = operation.column
    if operation.kind == "replace_values":
        pairs = ", ".join(
            f"{m.value!r}: {m.replacement!r}" for m in operation.mapping[:_RENDERED_MAPPINGS]
        )
        rest = len(operation.mapping) - _RENDERED_MAPPINGS
        note = f"  # +{rest} more mappings" if rest > 0 else ""
        return f'df["{column}"] = df["{column}"].replace({{{pairs}}}){note}'
    if operation.kind == "normalize_numeric":
        return f'df["{column}"] = normalize_numeric_format(df["{column}"])'
    if operation.kind == "normalize_date":
        return f'df["{column}"] = normalize_date_format(df["{column}"])'
    if operation.kind == "normalize_period":
        return f'df["{column}"] = normalize_period_format(df["{column}"])'
    if operation.kind == "strip_whitespace":
        return f'df["{column}"] = df["{column}"].astype("string").str.strip()'
    if operation.kind == "collapse_casing":
        return f'df["{column}"] = collapse_casing_variants(df["{column}"])'
    if operation.kind == "round_decimals":
        return f'df["{column}"] = pd.to_numeric(df["{column}"], errors="coerce").round({operation.digits})'
    if operation.kind == "cast_dtype":
        return f'df["{column}"], blocking = safe_cast(df["{column}"], "{operation.dtype}")'
    if operation.kind == "apply_generated_function":
        return f'{operation.source}\ndf["{column}"] = df["{column}"].map(clean_value)'
    if operation.kind == "impute_from_lookup":
        return (
            f'lookup = imputation_hints["{column}"]["mapping"]\n'
            f'predictor = imputation_hints["{column}"]["predictor_columns"][0]\n'
            f'df["{column}"] = df["{column}"].fillna(df[predictor].astype("string").map(lookup))'
        )
    if operation.kind == "drop_column":
        return f'df = df.drop(columns=["{column}"])'
    if operation.kind == "rename_column":
        return f'df = df.rename(columns={{"{column}": "{operation.new_name}"}})'
    if operation.kind == "drop_duplicate_rows":
        subset = f"subset={operation.subset}" if operation.subset else ""
        return f"df = df.drop_duplicates({subset})"
    return f"# unsupported operation: {operation.kind}"
