"""Tests for CompletenessAgent typed-issue migration (Step 9)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.completeness_agent import CompletenessAgent
from state_demo.issues import ISSUE_ADAPTER, IssueBase
from state_demo.pipeline_state import PipelineState


def _validate_each(issues: list[Any]) -> None:
    for issue in issues:
        assert isinstance(issue, IssueBase)
        ISSUE_ADAPTER.validate_python(issue.model_dump())


def test_completeness_agent_emits_typed_missing_values(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame(
        {
            "city": ["RM", "MI", None, None, "BO", None, "RM"] * 5,
            "zip": ["00100", "20100", "40100", "00100", "20100", "40100", "00100"] * 5,
        }
    )
    state.dataset_fingerprint = {"sparse_columns": []}
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    CompletenessAgent(state).run("completeness")

    issues = state.completeness_report["issues"]
    assert any(i.type == "missing_values" and i.column == "city" for i in issues)
    for issue in issues:
        assert issue.source == "completeness"
    _validate_each(issues)


def test_completeness_agent_detects_placeholder_values(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame({"note": ["ok", "n.d.", "n/a", "-", "fine", "?", "ok"] * 4})
    state.dataset_fingerprint = {"sparse_columns": []}
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    CompletenessAgent(state).run("completeness")

    issues = state.completeness_report["issues"]
    assert any(i.type == "placeholder_values" and i.column == "note" for i in issues)
    _validate_each(issues)
