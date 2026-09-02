"""Identifies the dataset's NoiPA domain, the most-likely dataset within that domain, and the primary language by sending a hierarchical signature map of the resolved baseline plus the input columns and sample values to the LLM. Implements the Profiler agent node."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from noipa_dq.models import BaselineFile
from noipa_dq.state import PipelineState
from noipa_dq.tools.baseline_accessors import domain_signatures
from noipa_dq.utils.llm import structured_model
from noipa_dq.utils.prompts import load_prompt


class _ProfilerResponse(BaseModel):
    detected_domain: str
    detected_language: str
    rationale: str


def profiler_node(state: PipelineState) -> PipelineState:
    baseline = _load_baseline(state)
    user_payload = _build_user_payload(state, baseline)

    chain = structured_model(_ProfilerResponse)

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
        "baseline_signatures": domain_signatures(baseline),
        "column_names": list(df.columns),
        "sample_values": {
            col: df[col].dropna().head(5).tolist()
            for col in df.columns
        },
    }
