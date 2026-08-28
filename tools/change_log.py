"""Audit trail of every change the pipeline makes to the data. Compares a dataframe before and after a transformation and records every value that changed, with the row, the column and what produced the change, so that the delivered dataset can be reconciled against the original. Records value changes cell by cell and type conversions once per column, since a cast rewrites every row without altering what the values mean. Used by the NaN handler, the Duplicate Column agent, the executor and the Apply step."""
from __future__ import annotations

import pandas as pd

_MISSING = "\x00"
_MAX_RECORDS = 20000


def diff_cells(
    before: pd.DataFrame, after: pd.DataFrame, source: str, limit: int = _MAX_RECORDS
) -> tuple[list[dict], int]:
    columns = [c for c in after.columns if c in before.columns]
    if not columns or len(before) != len(after):
        return [], 0

    records: list[dict] = []
    total = 0
    for column in columns:
        left = _comparable(before[column])
        right = _comparable(after[column])
        changed = left != right
        if not changed.any():
            continue
        total += int(changed.sum())
        for index in before.index[changed]:
            if len(records) >= limit:
                continue
            records.append({
                "scope": "cell",
                "row_index": int(index),
                "column": str(column),
                "before": _jsonable(before.at[index, column]),
                "after": _jsonable(after.at[index, column]),
                "source": source,
            })
    return records, total


def diff_values_only(
    before: pd.DataFrame, after: pd.DataFrame, source: str, limit: int = _MAX_RECORDS
) -> list[dict]:
    records: list[dict] = []
    for column in [c for c in after.columns if c in before.columns]:
        if str(before[column].dtype) != str(after[column].dtype):
            rewritten = int((_comparable(before[column]) != _comparable(after[column])).sum())
            records.append({
                "scope": "column",
                "row_index": -1,
                "column": str(column),
                "before": str(before[column].dtype),
                "after": f"{after[column].dtype} ({rewritten} values rewritten)",
                "source": f"{source}:dtype",
            })
            continue
        cells, _ = diff_cells(before[[column]], after[[column]], source, limit - len(records))
        records.extend(cells)
    return records


def _comparable(series: pd.Series) -> pd.Series:
    return series.astype(object).where(series.notna(), _MISSING).astype(str)


def _jsonable(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value
