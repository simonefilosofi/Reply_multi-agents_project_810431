"""Parses a numeric column written with human notation - currency symbols or codes, thousands separators, an Italian decimal comma - into plain numbers. Mirrors normalize_date_format: it changes representation, never magnitude, and is applied before any numeric cast so that a value written as an amount is not treated as uncastable."""
from __future__ import annotations

import re

import pandas as pd

_CURRENCY = re.compile(r"(?:^\s*[€$£]\s*)|(?:\s*(?:eur|euro|usd)\s*$)", re.IGNORECASE)
_DECIMAL_COMMA = re.compile(r"^-?\d+,\d+$")
_THOUSANDS_DOT = re.compile(r"^-?\d{1,3}(?:\.\d{3})+(?:,\d+)?$")
_THOUSANDS_COMMA = re.compile(r"^-?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")


def normalize_numeric_format(series: pd.Series) -> pd.Series:
    if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
        return series
    return series.map(_normalize)


def _normalize(value):
    if not isinstance(value, str):
        return value
    text = _CURRENCY.sub("", value.strip()).strip()
    if not text:
        return value
    if _THOUSANDS_DOT.match(text):
        return text.replace(".", "").replace(",", ".")
    if _THOUSANDS_COMMA.match(text):
        return text.replace(",", "")
    if _DECIMAL_COMMA.match(text):
        return text.replace(",", ".")
    return text
