"""Tests for AnomalyAgent typed-issue migration (Step 9)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.anomaly_agent import AnomalyAgent
from state_demo.issues import ISSUE_ADAPTER, IssueBase
from state_demo.pipeline_state import PipelineState


def _validate_each(issues: list[Any]) -> None:
    for issue in issues:
        assert isinstance(issue, IssueBase)
        ISSUE_ADAPTER.validate_python(issue.model_dump())


def test_anomaly_agent_typed_outliers(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    base = [10.0 + (i % 5) * 0.5 for i in range(30)]
    state.df_raw = pd.DataFrame({"amount": [*base, 10000.0]})
    state.dataset_fingerprint = {
        "numerical_columns": ["amount"],
        "categorical_columns": [],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    AnomalyAgent(state).run("anomalies")

    issues = state.anomaly_report["issues"]
    assert any(i.type == "outliers" and i.column == "amount" for i in issues)
    for issue in issues:
        assert issue.source == "anomaly"
    _validate_each(issues)


def test_anomaly_agent_typed_rare_categories(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame({"city": ["RM"] * 199 + ["AO"]})
    state.dataset_fingerprint = {
        "numerical_columns": [],
        "categorical_columns": ["city"],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    AnomalyAgent(state).run("anomalies")

    issues = state.anomaly_report["issues"]
    assert any(i.type == "rare_categories" and i.column == "city" for i in issues)
    _validate_each(issues)
