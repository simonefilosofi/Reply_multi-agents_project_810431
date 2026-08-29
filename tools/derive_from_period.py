"""Derives the year and month columns from a canonical accounting period. A period written as 202308 states its own year and month: a row whose year column says 2021 contradicts its key, and the correct value is arithmetic rather than a judgement. The columns are identified by how well they already agree with the derivation, never by name, so the same rule works on a dataset that calls them anything."""
from __future__ import annotations

import re

import pandas as pd

_CANONICAL_PERIOD = re.compile(r"^\d{6}$")
_RECOGNITION_SHARE = 0.8
_MIN_ROWS = 20


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
    period = _canonical(df, period_column)
    expected = period.str[:4] if part == "year" else period.str[4:6].str.lstrip("0")
    return df[column].mask(period.notna(), expected)


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
