"""LLM-driven inference of a per-column FormatSpec (regex / enum / range / date) from the actual sample. Used by the Format & Consistency agent so validation rules are grounded in the dataset rather than only in baseline schemas, catching dates and other patterns the baseline does not cover and overriding baseline specs when a column's content semantically diverges from its NoiPA namesake."""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel

from noipa_dq.models import (
    ColumnPayload,
    DateFormat,
    EnumFormat,
    FormatSpec,
    RangeFormat,
    RegexFormat,
)
from noipa_dq.utils.llm import EmptyModelResponse, structured_model
from noipa_dq.utils.prompts import load_prompt


_MAX_ANSWER_TOKENS = 1024


class _InferResponse(BaseModel):
    kind: Literal["regex", "enum", "range", "date", "none"]
    regex_pattern: str | None = None
    enum_values: list[str] | None = None
    range_min: float | None = None
    range_max: float | None = None
    date_strftime: str | None = None


def infer_format_spec(
    payload: ColumnPayload,
    baseline_hint: str | None,
    candidate: FormatSpec | None = None,
    extended_sample: list | None = None,
) -> FormatSpec | None:
    chain = structured_model(_InferResponse, max_tokens=_MAX_ANSWER_TOKENS)
    user = {
        "column_name": payload.column_name,
        "description": payload.description,
        "dtype": payload.dtype,
        "sample": payload.sample,
        "extended_sample": extended_sample or [],
        "baseline_hint": baseline_hint,
        "deterministic_candidate": candidate.model_dump() if candidate else None,
    }
    try:
        result: _InferResponse = chain.invoke([
            {"role": "system", "content": load_prompt("infer_format_spec")},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ])
    except EmptyModelResponse:
        return None
    return _to_spec(result)


def _to_spec(r: _InferResponse) -> FormatSpec | None:
    if r.kind == "regex" and r.regex_pattern:
        return RegexFormat(pattern=r.regex_pattern)
    if r.kind == "enum" and r.enum_values:
        return EnumFormat(values=r.enum_values)
    if r.kind == "range" and (r.range_min is not None or r.range_max is not None):
        return RangeFormat(min=r.range_min, max=r.range_max)
    if r.kind == "date" and r.date_strftime:
        return DateFormat(strftime_pattern=r.date_strftime)
    return None
