"""Shared helper functions for data quality checks used across multiple agents."""

import pandas as pd

from state_demo.constants import PLACEHOLDERS


def missing_mask(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    return series.isna() | (s == "") | s.str.lower().isin(PLACEHOLDERS)


def non_empty_values(series: pd.Series) -> pd.Series:
    s = series.dropna()
    return s[s.astype(str).str.strip() != ""]
