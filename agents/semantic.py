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
from tools.retrieve_canonical import lookup_descriptor, retrieve_top_k
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
_SENTINEL_MIN_DIGITS = 4
_PLACEHOLDER_LOOKUP = {p.lower().strip() if isinstance(p, str) else p for p in _PLACEHOLDERS}


class _SemanticResponse(BaseModel):
    dtype: str
    column_meaning: str
    placeholders: list[str | int | float]
    related_columns: list[str]
    target_casing: Casing
    canonical_match: str | None = None


class _ColumnDescription(BaseModel):
    column_name: str
    description: str


class _DescribeResponse(BaseModel):
    descriptions: list[_ColumnDescription]


def semantic_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset
    all_columns = list(df.columns)

    domain_catalog = column_catalog_all_domains(state.baseline) if state.baseline else {}
    aliases = alias_index(state.baseline) if state.baseline else {}
    chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0).with_structured_output(_SemanticResponse)
    system = load_prompt("semantic")
    descriptions = _describe_columns(df, all_columns)

    payload: list[ColumnPayload] = []
    for col in all_columns:
        series = df[col]
        non_null = series.dropna()
        sample = non_null.sample(n=min(30, non_null.shape[0]), random_state=42).tolist()
        description = descriptions.get(col, "")

        suggestion = programmatic_match(col, domain_catalog, aliases) if domain_catalog else None
        suggested_spec = find_spec_by_hint(state.baseline, suggestion) if state.baseline else None
        sentinels = _detect_numeric_sentinels(series)
        placeholder_cands = _detect_placeholder_candidates(series, suggested_spec, sentinels)
        canonical_cands = _retrieve_canonical_candidates(
            col, str(series.dtype), sample, state.baseline, description
        )

        user = {
            "column_name": col,
            "dataset_domain": state.detected_domain,
            "dtype": str(series.dtype),
            "sample": sample,
            "all_column_names": all_columns,
            "placeholder_candidates": placeholder_cands,
            "canonical_suggestion": _summarize_spec(suggestion, suggested_spec),
            "canonical_candidates": canonical_cands,
        }
        result: _SemanticResponse = chain.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
        ])

        canonical_hint = _validate_canonical_match(result.canonical_match)
        confirmed_spec = (
            find_spec_by_hint(state.baseline, canonical_hint)
            if state.baseline and canonical_hint != "NaN"
            else None
        )
        dtype = _resolve_dtype(canonical_hint, series, result.dtype)
        final_placeholders = _merge_placeholders(placeholder_cands, result.placeholders, sentinels)
        payload.append(ColumnPayload(
            column_name=col,
            description=result.column_meaning,
            dtype=dtype,
            sample=sample,
            placeholders=final_placeholders,
            related_columns=result.related_columns,
            target_casing=_resolve_casing(dtype, result.target_casing, confirmed_spec),
            canonical_hint=canonical_hint,
            canonical_candidates=canonical_cands,
        ))

    return state.model_copy(update={"payload": payload})


def _detect_numeric_sentinels(series: pd.Series) -> list:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return []
    extremes = {numeric.min(), numeric.max()}
    sentinels: list = []
    for value in extremes:
        digits = str(abs(int(value)))
        if len(digits) >= _SENTINEL_MIN_DIGITS and set(digits) == {"9"}:
            original = series[pd.to_numeric(series, errors="coerce") == value].dropna()
            if not original.empty:
                sentinels.append(original.iloc[0])
    return sentinels


def _detect_placeholder_candidates(series: pd.Series, spec: ColumnSchema | None, sentinels: list) -> list:
    matches: list = list(sentinels)
    seen: set = set(sentinels)
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


def _merge_placeholders(detected: list, llm_kept: list, sentinels: list) -> list:
    auto = [v for v in detected if isinstance(v, str)] + list(sentinels)
    merged: list = []
    seen: set = set()
    for v in auto + list(llm_kept):
        key = v.lower().strip() if isinstance(v, str) else v
        if key not in seen:
            seen.add(key)
            merged.append(v)
    return merged


def _validate_canonical_match(match: str | None) -> str:
    if not match:
        return "NaN"
    return match if lookup_descriptor(match) is not None else "NaN"


def _resolve_dtype(canonical_hint: str, series: pd.Series, llm_dtype: str) -> str:
    if canonical_hint != "NaN":
        descriptor = lookup_descriptor(canonical_hint)
        if descriptor and descriptor.get("dtype"):
            return descriptor["dtype"]
    return infer_and_validate_dtype(series, llm_suggestion=llm_dtype)



def _describe_columns(df: pd.DataFrame, columns: list[str]) -> dict[str, str]:
    chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0).with_structured_output(_DescribeResponse)
    user = {
        "columns": [
            {
                "column_name": col,
                "dtype": str(df[col].dtype),
                "sample": df[col].dropna().head(5).tolist(),
            }
            for col in columns
        ],
    }
    result: _DescribeResponse = chain.invoke([
        {"role": "system", "content": load_prompt("semantic_describe")},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False, default=str)},
    ])
    return {d.column_name: d.description for d in result.descriptions}


def _retrieve_canonical_candidates(
    name: str, dtype: str, samples: list, baseline, description: str = ""
) -> list[dict]:
    candidates = retrieve_top_k(name, dtype, samples, description=description, k=5)
    if baseline is None:
        return candidates
    for c in candidates:
        spec = find_spec_by_hint(baseline, c["canonical_id"])
        if spec:
            c["format"] = compact_format_summary(spec.format)
            c["case_convention"] = spec.case_convention
            c["is_nullable"] = spec.is_nullable
    return candidates


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
