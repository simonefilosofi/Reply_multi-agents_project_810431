"""Checks each value in a column against a per-column FormatSpec. Dispatches over RegexFormat (full-match against pattern), EnumFormat (membership against allowed values), RangeFormat (numeric bounds), and DateFormat (parseability against an strftime pattern via pd.to_datetime). A column already stored as datetime64 carries no textual layout, so its DateFormat check is skipped: the pattern would only describe how pandas renders the value, not whether the datum is valid. Each violation is surfaced through a uniform expected_pattern string consumed by the Format & Consistency agent."""
from __future__ import annotations

import re
from typing import Callable

import pandas as pd

from models import (
    DateFormat,
    EnumFormat,
    FormatSpec,
    FormatViolation,
    RangeFormat,
    RegexFormat,
    ValidationReport,
)


def validate_format(
    col_name: str,
    series: pd.Series,
    spec: FormatSpec | None,
) -> ValidationReport:
    if spec is None:
        return ValidationReport(column_name=col_name)
    if isinstance(spec, DateFormat) and pd.api.types.is_datetime64_any_dtype(series):
        return ValidationReport(column_name=col_name)

    is_valid, expected = _checker_for(spec)
    violations = [
        FormatViolation(
            column_name=col_name,
            row_index=int(idx),
            value=val,
            expected_pattern=expected,
            kind="format",
        )
        for idx, val in series.items()
        if pd.notna(val) and not is_valid(val)
    ]
    return ValidationReport(column_name=col_name, violations=violations)


def _checker_for(spec: FormatSpec) -> tuple[Callable[[object], bool], str]:
    if isinstance(spec, RegexFormat):
        compiled = re.compile(spec.pattern)
        return (lambda v: compiled.fullmatch(str(v)) is not None), spec.pattern
    if isinstance(spec, EnumFormat):
        allowed = {str(x) for x in spec.values}
        return (lambda v: str(v) in allowed), f"enum: {spec.values}"
    if isinstance(spec, RangeFormat):
        lo, hi = spec.min, spec.max
        return (lambda v: _in_range(v, lo, hi)), f"range: [{lo}, {hi}]"
    if isinstance(spec, DateFormat):
        fmt = spec.strftime_pattern
        return (lambda v: pd.notna(pd.to_datetime(str(v), format=fmt, errors="coerce"))), f"date: {fmt}"
    raise TypeError(f"Unsupported FormatSpec: {type(spec).__name__}")


def _in_range(value: object, lo: float | None, hi: float | None) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return (lo is None or x >= lo) and (hi is None or x <= hi)
