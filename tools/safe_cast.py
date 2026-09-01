"""Casts a column to a target dtype only when no non-null value would be lost, promoting a float declaration to an integer one when no value carries a decimal part, normalising human numeric and date notation first, and reporting the rows that block a cast rather than coercing them to NaN. A column naming only a year and a month is refused a date cast outright, because resolving it to the first of the month invents a day the file never stated. Also owns the pipeline's single notion of what a declaration means: declarations arrive in the canonical catalogue's vocabulary or in pandas' own names, and an integer cast lands on the nullable Int64, so dtype_family reduces both sides of a comparison to what a cast would produce and dtype_satisfied answers whether a column met its declaration. The NaN handler and the reliability score must agree on this, or correctly cast columns are marked untyped."""
from __future__ import annotations

import re

import pandas as pd

from tools.normalize_date_format import normalize_date_format
from tools.decimal_precision import recorded_precision
from tools.normalize_numeric_format import normalize_numeric_format

_DATE_TOKENS = ("date", "time")
_MONTH_PRECISION = re.compile(r"^(\d{4}[-/.]?\d{2}|\d{2}[-/.]\d{4})$")
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


def states_no_day(series: pd.Series) -> bool:
    """Whether every value names a year and a month and no day. Such a column is a period, and
    parsing it as a date resolves it to the first of the month - a value the file never held, and
    a precision it never claimed. The pipeline reads month-precision columns as periods elsewhere,
    so the cast is refused here and the values are left for that handling."""
    populated = series.dropna()
    if populated.empty:
        return False
    text = populated.astype(str).str.strip()
    return bool(text.str.fullmatch(_MONTH_PRECISION).all())


def dtype_family(dtype: str) -> str:
    """The family a dtype belongs to, whether written in the catalogue's vocabulary (integer,
    float, string), in pandas' names (int64, Int64, datetime64[ns]), or as anything else
    pandas accepts. Deciding it in one place keeps what a cast produces and what a reader
    expects of it from drifting apart."""
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
    """Whether a realised dtype meets a declaration. String equality cannot answer this:
    declarations are written either as a catalogue word or as a pandas name, and an integer
    cast lands on the nullable Int64, so the two are almost never spelled alike. A float
    declaration is met by an integer realisation because _refine promotes it when no value
    carries a decimal part."""
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
            if states_no_day(series):
                return None
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
