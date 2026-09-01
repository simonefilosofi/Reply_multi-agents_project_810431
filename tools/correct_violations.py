"""Per-column LLM-driven proposal of targeted value corrections for format violations. Takes the unique offending values plus the column's neighborhood (description, dtype, expected pattern, valid sample) and returns a {value -> corrected_value | null} map. Used by the Format & Consistency agent to feed the Unified Remediation agent value-preserving replace fixes (e.g. "Gen-2024" -> "202401") instead of generic null/zero/unknown imputations."""
from __future__ import annotations

import json

from pydantic import BaseModel

from models import ColumnPayload
from utils.llm import EmptyModelResponse, structured_model
from utils.prompts import load_prompt


_MAX_ANSWER_TOKENS = 4096


class _Correction(BaseModel):
    value: str
    corrected_value: str | None
    rationale: str


class _CorrectionsResponse(BaseModel):
    corrections: list[_Correction]


def correct_violations(
    payload: ColumnPayload,
    expected_pattern: str,
    offending_values: list[str],
    valid_sample: list[str],
) -> dict[str, str | None]:
    if not offending_values:
        return {}
    chain = structured_model(_CorrectionsResponse, max_tokens=_MAX_ANSWER_TOKENS)
    user = {
        "column_name": payload.column_name,
        "description": payload.description,
        "dtype": payload.dtype,
        "expected_pattern": expected_pattern,
        "valid_sample": valid_sample,
        "offending_values": offending_values,
    }
    try:
        result: _CorrectionsResponse = chain.invoke([
            {"role": "system", "content": load_prompt("correct_violations")},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ])
    except EmptyModelResponse:
        return {}
    return {c.value: c.corrected_value for c in result.corrections}
