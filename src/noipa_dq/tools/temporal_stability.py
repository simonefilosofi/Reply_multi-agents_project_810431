"""Tests whether a functional dependency holds steadily over time or shifts partway through the dataset. A public body that is renamed keeps its code but changes its description, so the mapping from code to name is a function of the period, not a constant. Treating such a dependency as fixed makes the pipeline impute the historically wrong value and report legitimate rows as inconsistent. Used by the imputation miner and by the cross-column checker."""
from __future__ import annotations

import pandas as pd

_MIN_ROWS_PER_PERIOD = 3


def time_column(df: pd.DataFrame, inferred_specs: dict | None = None) -> str | None:
    for column in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[column]):
            return str(column)
    for column, info in (inferred_specs or {}).items():
        spec = (info or {}).get("final_spec") or {}
        if spec.get("type") == "date" and column in df.columns:
            return str(column)
    return None


def is_stable(df: pd.DataFrame, predictor: str, target: str, clock: str | None) -> bool:
    if clock is None or clock in (predictor, target):
        return True
    usable = df[[predictor, target, clock]].dropna()
    if usable.empty:
        return True

    for key, block in usable.groupby(predictor):
        periods = sorted(block[clock].unique())
        if len(periods) < 2:
            continue
        first = _dominant(block[block[clock] == periods[0]], target)
        last = _dominant(block[block[clock] == periods[-1]], target)
        if first is None or last is None:
            continue
        if first != last:
            return False
    return True


def _dominant(block: pd.DataFrame, target: str):
    if len(block) < _MIN_ROWS_PER_PERIOD:
        return None
    return block[target].value_counts().idxmax()
