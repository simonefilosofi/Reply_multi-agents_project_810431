"""Produces a deterministic hash of a column's full sorted value set."""
from __future__ import annotations

import hashlib

import pandas as pd


def hash_column_values(series: pd.Series) -> str:
    values = sorted(series.dropna().astype(str).tolist())
    raw = "\n".join(values).encode()
    return hashlib.sha256(raw).hexdigest()
