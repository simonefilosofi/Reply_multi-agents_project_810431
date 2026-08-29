"""Normalises accounting periods written in mixed layouts into the canonical YYYYMM form. A period is a year and a month, so `2024-06`, `06/2024` and `GIU-2024` all denote the same thing and the conversion is arithmetic, not interpretation. Values whose month cannot be determined are left untouched, so they stay visible as violations. Mirrors normalize_date_format and normalize_numeric_format."""
from __future__ import annotations

import re

import pandas as pd

from tools.normalize_date_format import _ITALIAN_MONTHS

_ENGLISH_MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}
_MONTH_NAMES = {**_ENGLISH_MONTHS, **_ITALIAN_MONTHS}

_CANONICAL = re.compile(r"^(\d{4})(0[1-9]|1[0-2])$")
_YEAR_FIRST = re.compile(r"^(\d{4})[-/. ](\d{1,2})$")
_MONTH_FIRST = re.compile(r"^(\d{1,2})[-/. ](\d{4})$")
_NAMED_MONTH = re.compile(r"^([A-Za-z]{3,})[-/. ](\d{4})$")


def normalize_period_format(series: pd.Series) -> pd.Series:
    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return series
    return series.map(_normalize)


def _normalize(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if _CANONICAL.match(text):
        return text

    match = _YEAR_FIRST.match(text)
    if match:
        return _compose(match.group(1), match.group(2)) or value

    match = _MONTH_FIRST.match(text)
    if match:
        return _compose(match.group(2), match.group(1)) or value

    match = _NAMED_MONTH.match(text)
    if match:
        month = _MONTH_NAMES.get(match.group(1)[:3].lower())
        return f"{match.group(2)}{month}" if month else value

    return value


def _compose(year: str, month: str) -> str | None:
    if not month.isdigit() or not 1 <= int(month) <= 12:
        return None
    return f"{year}{int(month):02d}"


def is_canonical(series: pd.Series) -> pd.Series:
    """Which values already carry both a year and a month."""
    return series.astype("string").str.strip().str.fullmatch(_CANONICAL.pattern).fillna(False)
