"""Completeness analysis over a dataframe: per-column and dataset-wide fill rates, the distribution of missing values across rows, and the columns so empty that they are candidates for removal. Backs the Completeness Analysis performed by the NaN handler."""
from __future__ import annotations

import pandas as pd

_SPARSE_THRESHOLD = 0.9
_WORST_ROWS = 10


def completeness_report(df: pd.DataFrame, sparse_threshold: float = _SPARSE_THRESHOLD) -> dict:
    rows, columns = df.shape
    cells = rows * columns
    null_by_column = {str(column): int(df[column].isna().sum()) for column in df.columns}
    nulls_per_row = df.isna().sum(axis=1)

    return {
        "by_column": {
            column: {
                "nulls": nulls,
                "total": rows,
                "completeness": _rate(rows - nulls, rows),
            }
            for column, nulls in null_by_column.items()
        },
        "overall": {
            "rows": rows,
            "columns": columns,
            "cells": cells,
            "null_cells": int(sum(null_by_column.values())),
            "completeness": _rate(cells - sum(null_by_column.values()), cells),
        },
        "rows": {
            "complete_rows": int((nulls_per_row == 0).sum()),
            "rows_with_nulls": int((nulls_per_row > 0).sum()),
            "max_nulls_in_a_row": int(nulls_per_row.max()) if rows else 0,
            "worst_rows": [
                {"row_index": int(index), "nulls": int(count)}
                for index, count in nulls_per_row.nlargest(_WORST_ROWS).items()
                if count > 0
            ],
        },
        "sparse_columns": [
            {
                "column": column,
                "nulls": nulls,
                "null_rate": _rate(nulls, rows),
            }
            for column, nulls in null_by_column.items()
            if rows and nulls / rows >= sparse_threshold
        ],
    }


def _rate(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)
