"""Replaces values matching the payload placeholder list with NaN."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def detect_placeholders(series: pd.Series, placeholders: list[Any]) -> pd.Series:
    if not placeholders:
        return series
    return series.replace(placeholders, np.nan)
