"""Deterministic value-pattern profiler. Scans the entire column and emits a FormatSpec (date / range / enum / regex) when one shape dominates by a configurable threshold; otherwise returns None so the LLM-driven inferer can take over. Used by the Format & Consistency agent as the primary path so format detection is reproducible, language-agnostic, and not bottlenecked by sample-size inference."""
from __future__ import annotations

import re
import string
from collections import Counter

import pandas as pd

from models import DateFormat, EnumFormat, FormatSpec, RangeFormat, RegexFormat


_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d",
    "%Y%m%d", "%Y%m", "%m/%Y", "%m-%Y", "%Y",
    "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
]
_DOMINANCE = 0.85
_RARE_FLOOR = 0.01
_MIN_VALUES = 5
_MAX_ENUM = 30
_YEAR_MIN, _YEAR_MAX = 1500, 2200
_CLASS_REGEX = {"d": r"\d", "U": "[A-Z]", "l": "[a-z]"}
_CHAR_CLASS = {**{c: "d" for c in string.digits},
               **{c: "U" for c in string.ascii_uppercase},
               **{c: "l" for c in string.ascii_lowercase}}


def profile_format_spec(series: pd.Series, dominance: float = _DOMINANCE) -> FormatSpec | None:
    non_null = series.dropna()
    if len(non_null) < _MIN_VALUES:
        return None
    str_vals = non_null.astype(str)
    return (_try_date(str_vals, dominance)
            or _try_range(non_null, dominance)
            or _try_enum(non_null, dominance)
            or _try_regex(str_vals, dominance))


def _try_date(str_vals: pd.Series, dominance: float) -> DateFormat | None:
    n = len(str_vals)
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(str_vals, format=fmt, errors="coerce")
        valid = parsed.dropna()
        if len(valid) / n < dominance:
            continue
        years = valid.dt.year
        if (years >= _YEAR_MIN).all() and (years <= _YEAR_MAX).all():
            return DateFormat(strftime_pattern=fmt)
    return None


def _try_range(non_null: pd.Series, dominance: float) -> RangeFormat | None:
    parsed = pd.to_numeric(non_null, errors="coerce")
    valid = parsed.dropna()
    if len(valid) / len(non_null) < dominance:
        return None
    return RangeFormat(min=float(valid.min()), max=float(valid.max()))


def _try_enum(non_null: pd.Series, dominance: float) -> EnumFormat | None:
    n = len(non_null)
    counts = non_null.value_counts()
    common = counts[counts / n >= _RARE_FLOOR]
    if 1 < len(common) <= _MAX_ENUM and common.sum() / n >= dominance:
        return EnumFormat(values=[str(v) for v in common.index])
    return None


def _try_regex(str_vals: pd.Series, dominance: float) -> RegexFormat | None:
    sigs = [_signature(s) for s in str_vals]
    shape_counts = Counter(sh for sh, _ in sigs)
    top_shape, top_count = shape_counts.most_common(1)[0]
    if top_count / len(sigs) < dominance:
        return None
    return RegexFormat(pattern=next(rgx for sh, rgx in sigs if sh == top_shape))


def _signature(s: str) -> tuple[str, str]:
    shape: list[str] = []
    rgx: list[str] = ["^"]
    i, n = 0, len(s)
    while i < n:
        cls = _CHAR_CLASS.get(s[i])
        if cls:
            j = i
            while j < n and _CHAR_CLASS.get(s[j]) == cls:
                j += 1
            run = j - i
            shape.append(f"{cls}{{{run}}}")
            rgx.append(f"{_CLASS_REGEX[cls]}{{{run}}}")
            i = j
        else:
            shape.append(s[i])
            rgx.append(re.escape(s[i]))
            i += 1
    rgx.append("$")
    return "".join(shape), "".join(rgx)
