"""Casts a column to a target dtype only when no non-null value would be lost, reporting the row indices that block the cast instead of coercing them to NaN. Backs the non-destructive dtype enforcement performed by the NaN handler."""
from __future__ import annotations

import pandas as pd

from tools.normalize_date_format import normalize_date_format

_DATE_TOKENS = ("date", "time")
_FLOAT_TOKENS = ("float", "double", "decimal")


def safe_cast(series: pd.Series, dtype: str) -> tuple[pd.Series, list[int]]:
    target = dtype.lower()
    converted = _convert(series, target)
    if converted is None:
        return series, []

    lost = series.notna() & converted.isna()
    if lost.any():
        return series, [int(i) for i in series.index[lost]]
    return converted, []


def _convert(series: pd.Series, target: str) -> pd.Series | None:
    try:
        if any(token in target for token in _DATE_TOKENS):
            return normalize_date_format(series)
        if "int" in target:
            return pd.to_numeric(series, errors="coerce").astype("Int64")
        if any(token in target for token in _FLOAT_TOKENS):
            return pd.to_numeric(series, errors="coerce")
        if "bool" in target:
            return series.astype("boolean")
        if "string" in target or target == "object":
            return series.astype("string")
        return series.astype(target)
    except (ValueError, TypeError):
        return None
