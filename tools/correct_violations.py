"""Per-column LLM-driven proposal of targeted value corrections for format violations. Takes the unique offending values plus the column's neighborhood (description, dtype, expected pattern, valid sample) and returns a {value -> corrected_value | null} map. Used by the Format & Consistency agent to feed the Unified Remediation agent value-preserving replace fixes (e.g. "Gen-2024" -> "202401") instead of generic null/zero/unknown imputations."""
from __future__ import annotations

import json

from langchain_openai import ChatOpenAI
from openai import LengthFinishReasonError
from pydantic import BaseModel

from models import ColumnPayload
from utils.prompts import load_prompt


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
    chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0, max_tokens=4096).with_structured_output(_CorrectionsResponse)
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
    except LengthFinishReasonError:
        return {}
    return {c.value: c.corrected_value for c in result.corrections}
