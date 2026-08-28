"""Row-level duplicate analysis: identifies the columns that behave as record keys, counts exact duplicate rows, and finds records that collide on a key while differing elsewhere. Backs the Duplicate Detection performed by the Duplicate Row agent, which removes only exact duplicates and leaves key collisions for human review."""
from __future__ import annotations

import pandas as pd

_KEY_UNIQUENESS = 0.95
_MAX_KEY_COLUMNS = 2
_MAX_REPORTED_KEYS = 50


def key_columns(df: pd.DataFrame, max_keys: int = _MAX_KEY_COLUMNS) -> list[str]:
    ranked = []
    for column in df.columns:
        populated = int(df[column].notna().sum())
        if not populated:
            continue
        uniqueness = df[column].nunique(dropna=True) / populated
        if uniqueness >= _KEY_UNIQUENESS:
            ranked.append((-uniqueness, column))
    return [column for _, column in sorted(ranked)[:max_keys]]


def duplicate_row_analysis(df: pd.DataFrame) -> dict:
    exact = df.duplicated(keep="first")
    keys = key_columns(df)
    collisions = {}
    for key in keys:
        duplicated_keys = df[key][df[key].duplicated(keep=False) & df[key].notna()]
        if duplicated_keys.empty:
            continue
        conflicting = _conflicting_keys(df, key, duplicated_keys.unique())
        collisions[key] = {
            "duplicated_keys": int(duplicated_keys.nunique()),
            "affected_rows": int(duplicated_keys.shape[0]),
            "keys_with_conflicting_data": len(conflicting),
            "examples": [str(value) for value in conflicting[:_MAX_REPORTED_KEYS]],
        }
    return {
        "exact_duplicate_rows": int(exact.sum()),
        "key_columns": keys,
        "key_collisions": collisions,
    }


def _conflicting_keys(df: pd.DataFrame, key: str, values) -> list:
    conflicting = []
    others = [c for c in df.columns if c != key]
    for value in values:
        block = df.loc[df[key] == value, others]
        if len(block.drop_duplicates()) > 1:
            conflicting.append(value)
    return conflicting
