"""Produces a ColumnPayload for every column: programmatic placeholder candidate scan, LLM-based filtering, dtype-aware casing."""
from __future__ import annotations

import json

import pandas as pd
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import Casing, ColumnPayload
from state import PipelineState
from tools.infer_and_validate_dtype import infer_and_validate_dtype
from utils.prompts import load_prompt


_PLACEHOLDERS: list = [
    "",
    "-", "--", ".", "..", "...", "//", "///",
    "?", "??", "???", "#",
    "n/a", "na", "n.a.", "#n/a",
    "n/d", "nd", "n.d.", "#n/d", "#nd",
    "null", "none", "nan",
    "unknown", "missing", "tbd", "error",
    "not available", "not applicable",
    "n/c", "nc", "n.c.",
    "sconosciuto", "non disponibile", "non applicabile",
    "da verificare", "da definire", "da inserire", "da completare",
    "in attesa", "non pervenuto", "non rilevato", "non classificato",
    -1, 0, 999, -999, 9999, -9999, 99999, -99999,
]
_PLACEHOLDER_LOOKUP = {p.lower().strip() if isinstance(p, str) else p for p in _PLACEHOLDERS}


class _SemanticResponse(BaseModel):
    dtype: str
    column_meaning: str
    placeholders: list[str | int | float]
    related_columns: list[str]
    target_casing: Casing


def semantic_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset
    all_columns = list(df.columns)
    chain = ChatOpenAI(model="gpt-4o", temperature=0).with_structured_output(_SemanticResponse)
    system = load_prompt("semantic")

    payload: list[ColumnPayload] = []
    for col in all_columns:
        series = df[col]
        sample = series.dropna().head(10).tolist()
        candidates = _detect_placeholder_candidates(series)
        user = {
            "column_name": col,
            "dataset_domain": state.detected_domain,
            "dtype": str(series.dtype),
            "sample": sample,
            "all_column_names": all_columns,
            "placeholder_candidates": candidates,
        }
        result: _SemanticResponse = chain.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ])
        dtype = infer_and_validate_dtype(series, llm_suggestion=result.dtype)
        payload.append(ColumnPayload(
            column_name=col,
            domain=result.column_meaning,
            dtype=dtype,
            sample=sample,
            placeholders=result.placeholders,
            related_columns=result.related_columns,
            target_casing=_enforce_casing(dtype, result.target_casing),
        ))

    return state.model_copy(update={"payload": payload})


def _detect_placeholder_candidates(series: pd.Series) -> list:
    matches: list = []
    for value in series.dropna().unique():
        key = value.lower().strip() if isinstance(value, str) else value
        if key in _PLACEHOLDER_LOOKUP:
            matches.append(value)
    return matches


def _enforce_casing(dtype: str, llm_casing: Casing) -> Casing:
    if dtype == "object" or dtype.startswith(("string", "category")):
        return llm_casing
    return Casing.as_is
