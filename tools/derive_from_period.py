"""Derives the year and month columns from a canonical accounting period. A period written as 202308 states its own year and month, so a target that cannot be read as one - a month spelled out, a two-digit year - is filled by arithmetic rather than by judgement. A target that is itself well formed and still disagrees is a different matter: rewriting it decides that the period is the more trustworthy of two conflicting columns, which is a judgement the approval gate owns, so derive leaves those rows alone and contested_rows names them for reporting. The columns are identified by how well they already agree with the derivation, never by name, so the same rule works on a dataset that calls them anything."""
from __future__ import annotations

import re

import pandas as pd

_CANONICAL_PERIOD = re.compile(r"^\d{6}$")
_RECOGNITION_SHARE = 0.8
_MIN_ROWS = 20
_YEAR_RANGE = (1900, 2100)
_MONTH_RANGE = (1, 12)


def derivable_columns(df: pd.DataFrame, period_column: str) -> dict[str, str]:
    """Maps each column that the period explains to the part it holds: 'year' or 'month'."""
    period = _canonical(df, period_column)
    if period.notna().sum() < _MIN_ROWS:
        return {}

    parts = {"year": period.str[:4], "month": period.str[4:6].str.lstrip("0")}
    found: dict[str, str] = {}
    for column in df.columns:
        if column == period_column:
            continue
        values = df[column]
        for part, expected in parts.items():
            if part in found.values():
                continue
            if _agreement(values, expected) >= _RECOGNITION_SHARE:
                found[str(column)] = part
                break
    return found


def derive(df: pd.DataFrame, period_column: str, column: str, part: str) -> pd.Series:
    """The column with the rows its period explains filled in. Only rows whose current value
    cannot be read as the part are rewritten; a well-formed value that disagrees is left for
    contested_rows to report."""
    period = _canonical(df, period_column)
    expected = _expected(period, part)
    fillable = period.notna() & ~_well_formed(df[column], part)
    return df[column].mask(fillable, expected)


def contested_rows(df: pd.DataFrame, period_column: str, column: str, part: str) -> pd.Index:
    """Rows where the period and a well-formed target both parse and disagree. One of the two is
    wrong and the data does not say which, so these are reported rather than silently rewritten."""
    period = _canonical(df, period_column)
    expected = _expected(period, part)
    comparable = period.notna() & _well_formed(df[column], part)
    if not comparable.any():
        return df.index[[]]
    current = pd.to_numeric(df[column][comparable], errors="coerce")
    derived = pd.to_numeric(expected[comparable], errors="coerce")
    return df.index[comparable][(current != derived).fillna(False)]


def _expected(period: pd.Series, part: str) -> pd.Series:
    return period.str[:4] if part == "year" else period.str[4:6].str.lstrip("0")


def _well_formed(values: pd.Series, part: str) -> pd.Series:
    """Whether each value already reads as the part on its own, without consulting the period. A
    two-digit year is ambiguous rather than well formed, so it stays derivable."""
    low, high = _YEAR_RANGE if part == "year" else _MONTH_RANGE
    numeric = pd.to_numeric(values, errors="coerce")
    whole = numeric.notna() & (numeric % 1 == 0)
    return (whole & numeric.between(low, high)).fillna(False)


def _canonical(df: pd.DataFrame, period_column: str) -> pd.Series:
    text = df[period_column].astype("string").str.strip()
    return text.where(text.str.fullmatch(_CANONICAL_PERIOD).fillna(False))


def _agreement(values: pd.Series, expected: pd.Series) -> float:
    comparable = values.notna() & expected.notna()
    if not comparable.any():
        return 0.0
    left = pd.to_numeric(values[comparable], errors="coerce")
    right = pd.to_numeric(expected[comparable], errors="coerce")
    matching = (left == right) & left.notna() & right.notna()
    return float(matching.sum()) / int(comparable.sum())
