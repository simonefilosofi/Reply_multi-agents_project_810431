"""Coerces date columns to a consistent format as specified by the baseline."""
from __future__ import annotations

import pandas as pd


def normalize_date_format(series: pd.Series, target_format: str = "%Y-%m-%d") -> pd.Series:
    # TODO: detect source format automatically before coercing
    return pd.to_datetime(series, errors="coerce").dt.strftime(target_format)
