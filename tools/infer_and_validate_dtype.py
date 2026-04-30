"""Infers and validates a column's dtype via pandas, reconciling with the LLM suggestion."""
from __future__ import annotations

import pandas as pd


def infer_and_validate_dtype(series: pd.Series, llm_suggestion: str | None) -> str:
    inferred = str(series.dtype)
    if llm_suggestion and llm_suggestion != inferred:
        try:
            series.astype(llm_suggestion)
            return llm_suggestion
        except (ValueError, TypeError):
            pass
    return inferred
