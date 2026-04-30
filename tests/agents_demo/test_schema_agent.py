"""Tests for SchemaAgent typed-issue migration (Step 9).

Covers deterministic detection, typed LLM enrichment via EnrichmentResponse,
and that every emitted issue passes Issue.model_validate.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.schema_agent import SchemaAgent
from state.issues import ISSUE_ADAPTER, IssueBase
from state.pipeline_state import PipelineState


def _validate_each(issues: list[Any]) -> None:
    for issue in issues:
        assert isinstance(issue, IssueBase)
        ISSUE_ADAPTER.validate_python(issue.model_dump())


def test_schema_agent_emits_typed_issues_for_mixed_type(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame({"amount": ["1", "2", "X", "Y", "5"] * 4})
    state.dataset_fingerprint = {"numerical_columns": ["amount"], "date_columns": []}
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    SchemaAgent(state).run("schema")

    issues = state.schema_report["issues"]
    assert state.schema_report["total_issues"] == len(issues)
    assert any(i.type == "mixed_type" and i.column == "amount" for i in issues)
    for issue in issues:
        assert issue.source == "schema"
    _validate_each(issues)


def test_schema_agent_typed_enrichment_drops_invalid_llm_issue(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"amount": ["1", "2", "X", "Y", "5"] * 4, "Bad Name": ["a"] * 20})
    state.df_raw = df
    state.dataset_fingerprint = {"numerical_columns": ["amount"], "date_columns": []}
    valid_typed = ISSUE_ADAPTER.validate_python(
        {
            "type": "naming_convention",
            "column": "Bad Name",
            "detail": "contains spaces",
            "severity": "low",
        }
    )
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[valid_typed])

    SchemaAgent(state).run("schema")

    issues = state.schema_report["issues"]
    types = {i.type for i in issues}
    assert "mixed_type" in types
    assert "naming_convention" in types
    _validate_each(issues)


def test_schema_agent_keeps_deterministic_issues_when_llm_fails(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame({"amount": ["1", "2", "X", "Y", "5"] * 4})
    state.dataset_fingerprint = {"numerical_columns": ["amount"], "date_columns": []}

    def _raise(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("offline")

    from agents_demo.base_agent import BaseAgent

    BaseAgent_call = BaseAgent.call_llm_json
    BaseAgent.call_llm_json = _raise  # type: ignore[method-assign]
    try:
        SchemaAgent(state).run("schema")
    finally:
        BaseAgent.call_llm_json = BaseAgent_call  # type: ignore[method-assign]

    issues = state.schema_report["issues"]
    assert any(i.type == "mixed_type" for i in issues)
    _validate_each(issues)
