"""Determines the dataset's domain and primary language from the baseline context."""
from __future__ import annotations

import json
from pathlib import Path

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import BaselineFile
from state import PipelineState
from utils.prompts import load_prompt


class _ProfilerResponse(BaseModel):
    detected_domain: str
    detected_language: str
    rationale: str


def profiler_node(state: PipelineState) -> PipelineState:
    baseline = _load_baseline(state)
    user_payload = _build_user_payload(state, baseline)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    chain = llm.with_structured_output(_ProfilerResponse)

    result: _ProfilerResponse = chain.invoke([
        {"role": "system", "content": load_prompt("profiler")},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ])

    return state.model_copy(update={
        "baseline": baseline,
        "detected_domain": result.detected_domain,
        "detected_language": result.detected_language,
    })


def _load_baseline(state: PipelineState) -> BaselineFile:
    if state.baseline is not None:
        return state.baseline
    raw = Path(state.baseline_path).read_text(encoding="utf-8")
    return BaselineFile.model_validate_json(raw)


def _build_user_payload(state: PipelineState, baseline: BaselineFile) -> dict:
    df = state.dataset
    return {
        "baseline_domains": [d.domain for d in baseline.domains],
        "column_names": list(df.columns),
        "sample_values": {
            col: df[col].dropna().head(5).tolist()
            for col in df.columns
        },
    }
