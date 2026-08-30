"""Casts a column to a target dtype only when no non-null value would be lost, promoting a float declaration to an integer one when the values carry no decimal part, and normalising human numeric and date notation first so that a value written as an amount or a local-format date is not mistaken for uncastable, reporting the row indices that block the cast instead of coercing them to NaN. Owns the pipeline's single notion of what a dtype declaration means: a declaration arrives either in the canonical catalogue's vocabulary or in pandas' own names, and an integer cast deliberately lands on the nullable Int64, so dtype_family reduces both sides of any comparison to what a cast would produce and dtype_satisfied answers whether a realised column met its declaration. Backs the non-destructive dtype enforcement performed by the NaN handler and the dtype term of the reliability score, which must agree on conformity or mark correctly cast columns as untyped."""
from __future__ import annotations

import pandas as pd

from tools.normalize_date_format import normalize_date_format
from tools.decimal_precision import recorded_precision
from tools.normalize_numeric_format import normalize_numeric_format

_DATE_TOKENS = ("date", "time")
_FLOAT_TOKENS = ("float", "double", "decimal")


def safe_cast(series: pd.Series, dtype: str) -> tuple[pd.Series, list[int]]:
    target = _refine(series, dtype.lower())
    converted = _convert(series, target)
    if converted is None:
        return series, []

    lost = series.notna() & converted.isna()
    if lost.any():
        return series, [int(i) for i in series.index[lost]]
    return converted, []


def dtype_family(dtype: str) -> str:
    """The family a dtype belongs to, whether it is written in the canonical catalogue's
    vocabulary (integer, float, string), in pandas' own names (int64, Int64, datetime64[ns]), or
    as anything else pandas accepts. Deciding the family in one place is what keeps what a cast
    produces and what a reader expects of it from drifting apart."""
    target = (dtype or "").lower()
    if any(token in target for token in _DATE_TOKENS):
        return "datetime"
    if "int" in target:
        return "integer"
    if any(token in target for token in _FLOAT_TOKENS):
        return "float"
    if "bool" in target:
        return "boolean"
    if "string" in target or target == "object":
        return "string"
    return target


def dtype_satisfied(declared: str, realised: str) -> bool:
    """Whether a column that came out as realised meets what was declared for it. String equality
    cannot answer this: a declaration is written either as a catalogue word or as a pandas name,
    and an integer cast lands on the nullable Int64, so the two sides are almost never spelled
    alike. A float declaration is met by an integer realisation because _refine promotes it when
    no value carries a decimal part, which makes the integer the caster obeying the declaration."""
    wanted, got = dtype_family(declared), dtype_family(realised)
    return got == wanted or (wanted == "float" and got == "integer")


def _refine(series: pd.Series, target: str) -> str:
    """A count declared as a float comes back as 40.0 for every row. When the values carry no
    decimal part at all, the column is an integer whatever the declared type says."""
    if dtype_family(target) != "float":
        return target
    return "int64" if recorded_precision(series) == 0 else target


def _convert(series: pd.Series, target: str) -> pd.Series | None:
    family = dtype_family(target)
    try:
        if family == "datetime":
            return normalize_date_format(series)
        if family == "integer":
            return pd.to_numeric(normalize_numeric_format(series), errors="coerce").astype("Int64")
        if family == "float":
            return pd.to_numeric(normalize_numeric_format(series), errors="coerce")
        if family == "boolean":
            return series.astype("boolean")
        if family == "string":
            return series.astype("string")
        return series.astype(target)
    except (ValueError, TypeError):
        return None
