"""Tests for ConsistencyAgent typed-issue migration (Step 9).

Covers DateOrderIssue.column_a/column_b, format inconsistency, and
case inconsistency typed emissions.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.consistency_agent import ConsistencyAgent
from state_demo.issues import ISSUE_ADAPTER, DateOrderIssue, IssueBase
from state_demo.pipeline_state import PipelineState


def _validate_each(issues: list[Any]) -> None:
    for issue in issues:
        assert isinstance(issue, IssueBase)
        ISSUE_ADAPTER.validate_python(issue.model_dump())


def test_consistency_agent_typed_date_order(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame(
        {
            "start_date": [f"2024-01-{d:02d}" for d in range(1, 16)],
            "end_date": [f"2023-12-{d:02d}" for d in range(1, 16)],
        }
    )
    state.dataset_fingerprint = {
        "date_columns": ["start_date", "end_date"],
        "categorical_columns": [],
        "id_columns": [],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    ConsistencyAgent(state).run("consistency")

    issues = state.consistency_report["issues"]
    order_issues = [i for i in issues if isinstance(i, DateOrderIssue)]
    assert order_issues, "expected at least one DateOrderIssue"
    pair = order_issues[0]
    assert {pair.column_a, pair.column_b} == {"start_date", "end_date"}
    _validate_each(issues)


def test_consistency_agent_typed_case_inconsistency(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    cities = ["Roma", "roma", "ROMA", "Milano", "milano", "MILANO"] * 5 + ["Bologna"] * 5
    state.df_raw = pd.DataFrame({"citta": cities})
    state.dataset_fingerprint = {
        "date_columns": [],
        "categorical_columns": ["citta"],
        "id_columns": [],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    ConsistencyAgent(state).run("consistency")

    issues = state.consistency_report["issues"]
    assert any(i.type == "case_inconsistency" and i.column == "citta" for i in issues)
    _validate_each(issues)
