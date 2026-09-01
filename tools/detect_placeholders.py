"""Replaces values matching the payload placeholder list with NaN. Comparison ignores surrounding whitespace, since a value written as '? ' is the same placeholder as '?', but never ignores case: in a column of Italian province codes 'Na' is Naples, not the token 'na'."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def detect_placeholders(series: pd.Series, placeholders: list[Any]) -> pd.Series:
    if not placeholders:
        return series
    tokens = {str(value).strip() for value in placeholders}
    matched = series.astype("string").str.strip().isin(tokens)
    return series.mask(matched.fillna(False), np.nan)
