"""Infers and validates a column's dtype via pandas, reconciling with the LLM suggestion."""
from __future__ import annotations

import pandas as pd

_NUMERIC_PREFIXES = ("int", "float", "uint", "Int", "Float", "UInt")
_COERCION_THRESHOLD = 0.9


def infer_and_validate_dtype(series: pd.Series, llm_suggestion: str | None) -> str:
    inferred = str(series.dtype)
    if not llm_suggestion or llm_suggestion == inferred:
        return inferred
    try:
        series.astype(llm_suggestion)
        return llm_suggestion
    except (ValueError, TypeError):
        pass
    if llm_suggestion.startswith(_NUMERIC_PREFIXES):
        if pd.to_numeric(series, errors="coerce").notna().mean() >= _COERCION_THRESHOLD:
            return llm_suggestion
    if "datetime" in llm_suggestion.lower():
        if pd.to_datetime(series, errors="coerce").notna().mean() >= _COERCION_THRESHOLD:
            return llm_suggestion
    return inferred
