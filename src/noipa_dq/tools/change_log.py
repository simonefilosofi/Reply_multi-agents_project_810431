"""Audit trail of every change the pipeline makes to the data. Compares a dataframe before and after a transformation and records every value that changed, with the row, the column and what produced the change, so that the delivered dataset can be reconciled against the original. Records value changes cell by cell and type conversions once per column, since a cast rewrites every row without altering what the values mean. Used by the NaN handler, the Duplicate Column agent, the executor and the Apply step. Also summarises the same comparison per column, following approved renames, for the approval gate to show what an apply did."""
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


def column_diff(before, after, renames: dict[str, str]) -> list[dict]:
    """A column-by-column before and after, for the approval gate to show once fixes are applied.
    Columns are followed through the renames an approved fix performed, because looking a column
    up afterwards by the name it had before loses every renamed one: the row for the old name has
    nothing beside it and the new name has no row at all, which reads as the apply having done
    nothing. Columns only one side holds are still listed, marked for which side that is."""
    rows: list[dict] = []
    for column in before.columns:
        target = renames.get(str(column), str(column))
        present = target in after.columns
        rows.append({
            "column": str(column) if target == str(column) else f"{column} -> {target}",
            "status": "kept" if present else "removed",
            "nulls before": int(before[column].isna().sum()),
            "nulls after": int(after[target].isna().sum()) if present else None,
            "distinct before": int(before[column].nunique(dropna=True)),
            "distinct after": int(after[target].nunique(dropna=True)) if present else None,
        })
    accounted = {renames.get(str(c), str(c)) for c in before.columns}
    for column in after.columns:
        if str(column) in accounted:
            continue
        rows.append({
            "column": str(column), "status": "added",
            "nulls before": None, "nulls after": int(after[column].isna().sum()),
            "distinct before": None, "distinct after": int(after[column].nunique(dropna=True)),
        })
    return rows
