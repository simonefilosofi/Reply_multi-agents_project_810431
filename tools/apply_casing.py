"""Applies the target_casing directive from the payload to a string column."""
from __future__ import annotations

import pandas as pd

from models import Casing


def apply_casing(series: pd.Series, casing: Casing) -> pd.Series:
    if casing == Casing.lowercase:
        return series.str.lower()
    if casing == Casing.uppercase:
        return series.str.upper()
    return series
