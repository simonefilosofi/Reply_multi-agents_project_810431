"""Parses a date column whose values follow heterogeneous layouts into a single datetime series, trying a list of candidate formats before falling back to pandas inference. Used by the NaN handler before any datetime cast so that recoverable dates are not silently coerced to NaT."""
from __future__ import annotations

import re

import pandas as pd

_ITALIAN_MONTHS: dict[str, str] = {
    "gen": "01", "feb": "02", "mar": "03", "apr": "04", "mag": "05", "giu": "06",
    "lug": "07", "ago": "08", "set": "09", "ott": "10", "nov": "11", "dic": "12",
}
_MONTH_TOKEN = re.compile(r"\b(" + "|".join(_ITALIAN_MONTHS) + r")\w*\b", re.IGNORECASE)

_CANDIDATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d-%m-%y",
    "%d/%m/%y",
    "%d.%m.%y",
    "%Y%m%d",
    "%Y%m",
    "%m %d %Y",
    "%m-%d-%Y",
    "%d %m %Y",
)


def normalize_date_format(series: pd.Series) -> pd.Series:
    series = _replace_italian_months(series)
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    remaining = series.notna()

    for fmt in _CANDIDATE_FORMATS:
        if not remaining.any():
            break
        attempt = pd.to_datetime(series[remaining], format=fmt, errors="coerce")
        matched = attempt.notna()
        if not matched.any():
            continue
        parsed.loc[attempt.index[matched]] = attempt[matched]
        remaining.loc[attempt.index[matched]] = False

    if remaining.any():
        attempt = pd.to_datetime(series[remaining], errors="coerce", format="mixed", dayfirst=True)
        matched = attempt.notna()
        if matched.any():
            parsed.loc[attempt.index[matched]] = attempt[matched]

    return parsed


def _replace_italian_months(series: pd.Series) -> pd.Series:
    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return series
    return series.map(
        lambda v: _MONTH_TOKEN.sub(lambda m: _ITALIAN_MONTHS[m.group(1).lower()], v)
        if isinstance(v, str) else v
    )
