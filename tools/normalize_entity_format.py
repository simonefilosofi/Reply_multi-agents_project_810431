"""Standardizes string fields representing organization names to a canonical form."""
from __future__ import annotations

import re

import pandas as pd

_PREFIXES = re.compile(r"\b(ente|comune|provincia|regione|ministero)\b", re.IGNORECASE)


def normalize_entity_format(series: pd.Series) -> pd.Series:
    # TODO: expand rules and align with baseline entity vocabulary
    def _normalize(val: str) -> str:
        val = val.strip()
        val = _PREFIXES.sub(lambda m: m.group().title(), val)
        return val

    return series.dropna().map(_normalize).reindex(series.index)
