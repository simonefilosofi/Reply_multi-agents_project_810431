"""Collapses values that differ only by casing or surrounding whitespace onto a single canonical form, preferring the spelling declared by the column's enum spec and otherwise the most frequent variant. Applied deterministically after remediation so that no fix can leave a column split across spellings of the same value."""
from __future__ import annotations

import pandas as pd

from models import EnumFormat, FormatSpec


def collapse_casing_variants(series: pd.Series, spec: FormatSpec | None = None) -> pd.Series:
    values = series.dropna()
    if values.empty or not pd.api.types.is_string_dtype(values.astype("string")):
        return series

    text = values.astype("string")
    keys = text.str.strip().str.casefold()
    canonical_by_key = _canonical_forms(text, keys, spec)

    mapping = {
        original: canonical_by_key[key]
        for original, key in zip(text, keys)
        if canonical_by_key.get(key) is not None and original != canonical_by_key[key]
    }
    if not mapping:
        return series
    return series.replace(mapping)


def _canonical_forms(
    text: pd.Series, keys: pd.Series, spec: FormatSpec | None
) -> dict[str, str]:
    declared = {}
    if isinstance(spec, EnumFormat):
        declared = {str(v).strip().casefold(): str(v) for v in spec.values}

    canonical: dict[str, str] = {}
    for key, group in text.groupby(keys):
        if key in declared:
            canonical[key] = declared[key]
            continue
        counts = group.value_counts()
        top = counts.max()
        canonical[key] = sorted(counts[counts == top].index)[0]
    return canonical
