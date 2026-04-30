"""Produces a ColumnPayload for every column via LLM, then validates dtype programmatically."""
from __future__ import annotations

import json

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import Casing, ColumnPayload
from state import PipelineState
from tools.infer_and_validate_dtype import infer_and_validate_dtype
from utils.prompts import load_prompt


class _SemanticResponse(BaseModel):
    dtype: str
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
        user = {
            "column_name": col,
            "domain": state.detected_domain,
            "dtype": str(series.dtype),
            "sample": sample,
            "all_column_names": all_columns,
        }
        result: _SemanticResponse = chain.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ])
        payload.append(ColumnPayload(
            column_name=col,
            domain=state.detected_domain,
            dtype=infer_and_validate_dtype(series, llm_suggestion=result.dtype),
            sample=sample,
            placeholders=result.placeholders,
            related_columns=result.related_columns,
            target_casing=result.target_casing,
        ))

    return state.model_copy(update={"payload": payload})
