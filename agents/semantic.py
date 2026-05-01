"""Per-column Semantic agent: resolves each input column to a canonical NoiPA registry definition via a programmatic match cascade plus an LLM verdict, asks the LLM to validate dtype, filter placeholder candidates (curated tokens plus spec violations), identify related columns, and pick a target casing. Populates ColumnPayload.canonical_hint for downstream agents."""
from __future__ import annotations

import json

import pandas as pd
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import Casing, ColumnPayload, ColumnSchema, EnumFormat, RangeFormat
from state import PipelineState
from tools.baseline_accessors import (
    alias_index,
    column_catalog_all_domains,
    find_spec_by_hint,
)
from tools.infer_and_validate_dtype import infer_and_validate_dtype
from tools.match_canonical import compact_format_summary, programmatic_match
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
    canonical_match: str | None = None


def semantic_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset
    all_columns = list(df.columns)

    domain_catalog = column_catalog_all_domains(state.baseline) if state.baseline else {}
    aliases = alias_index(state.baseline) if state.baseline else {}
    chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(_SemanticResponse)
    system = load_prompt("semantic")

    payload: list[ColumnPayload] = []
    for col in all_columns:
        series = df[col]
        non_null = series.dropna()
        sample = non_null.sample(n=min(30, non_null.shape[0]), random_state=42).tolist()

        suggestion = programmatic_match(col, domain_catalog, aliases) if domain_catalog else None
        suggested_spec = find_spec_by_hint(state.baseline, suggestion) if state.baseline else None
        candidates = _detect_placeholder_candidates(series, suggested_spec)

        user = {
            "column_name": col,
            "dataset_domain": state.detected_domain,
            "dtype": str(series.dtype),
            "sample": sample,
            "all_column_names": all_columns,
            "placeholder_candidates": candidates,
            "canonical_suggestion": _summarize_spec(suggestion, suggested_spec),
            "domain_catalog": _compact_catalog(domain_catalog) if domain_catalog and suggested_spec is None else None,
        }
        result: _SemanticResponse = chain.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ])

        canonical_hint = result.canonical_match or None
        confirmed_spec = find_spec_by_hint(state.baseline, canonical_hint) if state.baseline else None
        dtype = infer_and_validate_dtype(series, llm_suggestion=result.dtype)
        payload.append(ColumnPayload(
            column_name=col,
            domain=result.column_meaning,
            dtype=dtype,
            sample=sample,
            placeholders=result.placeholders,
            related_columns=result.related_columns,
            target_casing=_resolve_casing(dtype, result.target_casing, confirmed_spec),
            canonical_hint=canonical_hint,
        ))

    return state.model_copy(update={"payload": payload})


def _detect_placeholder_candidates(series: pd.Series, spec: ColumnSchema | None) -> list:
    matches: list = []
    seen: set = set()
    for value in series.dropna().unique():
        key = value.lower().strip() if isinstance(value, str) else value
        if key in _PLACEHOLDER_LOOKUP and value not in seen:
            matches.append(value)
            seen.add(value)
    if spec is not None and spec.format is not None:
        for value in _spec_violations(series, spec):
            if value not in seen:
                matches.append(value)
                seen.add(value)
    return matches


def _spec_violations(series: pd.Series, spec: ColumnSchema) -> list:
    fmt = spec.format
    if isinstance(fmt, EnumFormat):
        allowed = set(fmt.values)
        return [v for v in series.dropna().unique() if v not in allowed]
    if isinstance(fmt, RangeFormat):
        out: list = []
        for v in series.dropna().unique():
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            if (fmt.min is not None and num < fmt.min) or (fmt.max is not None and num > fmt.max):
                out.append(v)
        return out
    return []


def _summarize_spec(canonical_id: str | None, spec: ColumnSchema | None) -> dict | None:
    if not canonical_id or spec is None:
        return None
    return {
        "canonical_id": canonical_id,
        "dtype": spec.dtype,
        "format": compact_format_summary(spec.format),
        "case_convention": spec.case_convention,
        "is_nullable": spec.is_nullable,
    }


def _compact_catalog(catalog: dict[str, ColumnSchema]) -> dict[str, dict]:
    return {
        name: {
            "canonical_id": schema.canonical_id or name,
            "dtype": schema.dtype,
            "format": compact_format_summary(schema.format),
            "case_convention": schema.case_convention,
            "is_nullable": schema.is_nullable,
        }
        for name, schema in catalog.items()
    }


def _resolve_casing(dtype: str, llm_casing: Casing, spec: ColumnSchema | None) -> Casing:
    if dtype != "object" and not dtype.startswith(("string", "category")):
        return Casing.as_is
    if spec and spec.case_convention:
        cc = spec.case_convention
        if cc.startswith("UPPER"):
            return Casing.uppercase
        if cc.startswith("lower"):
            return Casing.lowercase
        return Casing.as_is
    return llm_casing
