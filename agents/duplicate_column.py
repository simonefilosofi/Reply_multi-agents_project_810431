"""Detects exact and near-duplicate columns via pairwise similarity, fills gaps from sibling columns, and elects the canonical name via LLM over the full group."""
from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import DuplicateResolution
from state import PipelineState
from utils.prompts import load_prompt


_SIMILARITY_THRESHOLD = 0.80


class _NameElection(BaseModel):
    canonical_name: str
    rationale: str


def duplicate_column_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset
    groups = [g for g in _find_groups(list(df.columns), df) if len(g) > 1]
    if not groups:
        return state.model_copy(update={"surviving_columns": list(df.columns)})

    chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(_NameElection)
    system = load_prompt("duplicate_column")
    baseline_columns = _baseline_columns_for_domain(state)

    new_df = df.copy()
    dropped: set[str] = set()
    renames: dict[str, str] = {}
    resolutions: list[DuplicateResolution] = []

    for group in groups:
        nan_counts = {c: new_df[c].isna().sum() for c in group}
        min_nan = min(nan_counts.values())
        data_survivor = next(c for c, n in nan_counts.items() if n == min_nan)
        election = _llm_pick(chain, system, group, state.detected_domain, baseline_columns)

        for c in group:
            if c == data_survivor:
                continue
            mask = new_df[data_survivor].isna() & new_df[c].notna()
            new_df.loc[mask, data_survivor] = new_df.loc[mask, c]

        dropped.update(c for c in group if c != data_survivor)
        if election.canonical_name != data_survivor:
            renames[data_survivor] = election.canonical_name

        resolutions.append(DuplicateResolution(
            group=group,
            data_survivor=data_survivor,
            canonical_name=election.canonical_name,
            rationale=election.rationale,
            dropped=[c for c in group if c != data_survivor],
        ))

    new_df = new_df.drop(columns=list(dropped))
    if renames:
        new_df = new_df.rename(columns=renames)

    new_payload = [
        p.model_copy(update={"column_name": renames[p.column_name]}) if p.column_name in renames else p
        for p in state.payload
        if p.column_name not in dropped
    ]
    return state.model_copy(update={
        "dataset": new_df,
        "surviving_columns": list(new_df.columns),
        "payload": new_payload,
        "duplicate_resolutions": resolutions,
    })


def _find_groups(columns: list[str], df: pd.DataFrame) -> list[list[str]]:
    parent = {c: c for c in columns}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i, a in enumerate(columns):
        for b in columns[i + 1:]:
            if _similarity(df[a], df[b]) >= _SIMILARITY_THRESHOLD:
                union(a, b)

    grouped: dict[str, list[str]] = defaultdict(list)
    for c in columns:
        grouped[find(c)].append(c)
    return list(grouped.values())


def _similarity(a: pd.Series, b: pd.Series) -> float:
    overlap = a.notna() & b.notna()
    if not overlap.any():
        return 0.0
    a_n = a[overlap].astype("string").str.strip().str.lower()
    b_n = b[overlap].astype("string").str.strip().str.lower()
    return float((a_n == b_n).mean())


def _llm_pick(chain, system: str, group: list[str], domain: str, baseline_columns: list[str]) -> _NameElection:
    result: _NameElection = chain.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps({
            "duplicate_group": group,
            "domain": domain,
            "baseline_columns": baseline_columns,
        }, ensure_ascii=False)},
    ])
    if result.canonical_name not in group:
        return _NameElection(canonical_name=group[0], rationale=result.rationale)
    return result


def _baseline_columns_for_domain(state: PipelineState) -> list[str]:
    if state.baseline is None or not state.detected_domain:
        return []
    for d in state.baseline.domains:
        if d.domain == state.detected_domain:
            return [c.column_name for c in d.columns]
    return []
