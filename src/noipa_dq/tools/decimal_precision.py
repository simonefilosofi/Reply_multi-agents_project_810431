"""Detects the decimal precision a numeric column was actually recorded at, and separates it from floating-point representation noise. An amount stored as 182904.47999999954 is 182904.48 that survived a binary round-trip: the extra digits carry no information and make the column read as if it held sub-cent precision. Rounding is only proposed when the column shows a clear precision and when applying it leaves the totals intact, so a column of genuine high-precision measurements is left alone."""
from __future__ import annotations

import pandas as pd

_DOMINANT_SHARE = 0.5
_MAX_PRECISION = 6
_TOTAL_TOLERANCE = 1e-9


def recorded_precision(series: pd.Series) -> int | None:
    """The smallest number of decimals that already covers most of the column, when the values
    above it are far enough away to be noise rather than finer measurements. Returns 0 for
    whole numbers, and None when the spread suggests genuine measurement rather than
    representation noise."""
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None

    decimals = numeric.map(_decimals)
    for precision in range(_MAX_PRECISION + 1):
        covered = float((decimals <= precision).mean())
        if covered < _DOMINANT_SHARE:
            continue
        if _has_intermediate_values(decimals, precision):
            return None
        return precision
    return None


def rounds_cleanly(series: pd.Series, precision: int) -> bool:
    """Rounding must remove noise, not information: the column total has to survive it."""
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return False
    total = float(numeric.sum())
    rounded = float(numeric.round(precision).sum())
    scale = max(abs(total), 1.0)
    return abs(total - rounded) / scale <= _TOTAL_TOLERANCE


def _has_intermediate_values(decimals: pd.Series, precision: int) -> bool:
    """A column recorded at four decimals has values at three; one carrying float noise jumps
    straight from two to ten. The gap is what tells them apart."""
    above = decimals[decimals > precision]
    return bool(not above.empty and above.min() <= precision + 2)


def _decimals(value: float) -> int:
    text = repr(float(value))
    if "e" in text or "E" in text or "." not in text:
        return 0
    return len(text.split(".")[1].rstrip("0"))
