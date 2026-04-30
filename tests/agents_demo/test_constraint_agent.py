"""Tests for ConstraintAgent typed-issue migration (Step 9).

The B1 closure-relevant case lives in tests/integration/test_format_pattern_e2e.py;
this file unit-tests the agent itself: typed handler dispatch, structural
preservation of the pattern field, and Pydantic validation.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.constraint_agent import ConstraintAgent
from state.issues import ISSUE_ADAPTER, FormatPatternViolationIssue, IssueBase
from state.pipeline_state import PipelineState


def _validate_each(issues: list[Any]) -> None:
    for issue in issues:
        assert isinstance(issue, IssueBase)
        ISSUE_ADAPTER.validate_python(issue.model_dump())


def test_constraint_agent_emits_format_pattern_with_pattern_field(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame({"periodo": ["202401", "202402", "BAD", "202404", "x"]})
    state.dataset_fingerprint = {
        "numerical_columns": [],
        "categorical_columns": [],
        "column_constraints": [
            {
                "column": "periodo",
                "type": "format_pattern",
                "pattern": r"^\d{6}$",
                "description": "YYYYMM period code",
            }
        ],
    }
    state.schema_report = {"issues": [], "total_issues": 0}
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    ConstraintAgent(state).run("constraints")

    issues = state.constraint_report["issues"]
    pattern_issues = [i for i in issues if isinstance(i, FormatPatternViolationIssue)]
    assert pattern_issues, "expected at least one FormatPatternViolationIssue"
    issue = pattern_issues[0]
    assert issue.pattern == r"^\d{6}$"
    assert issue.description == "YYYYMM period code"
    assert issue.source == "constraint"
    _validate_each(issues)


def test_constraint_agent_handles_must_equal_column_typed(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame(
        {
            "nome": ["A", "B", "C", "D", "E", "F"],
            "name": ["A", "B", "X", "D", "Y", "F"],
        }
    )
    state.dataset_fingerprint = {
        "numerical_columns": [],
        "categorical_columns": [],
        "column_constraints": [
            {
                "column": "nome",
                "type": "must_equal_column",
                "other_column": "name",
                "description": "denormalised duplicate",
            }
        ],
    }
    state.schema_report = {"issues": [], "total_issues": 0}
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    ConstraintAgent(state).run("constraints")

    issues = state.constraint_report["issues"]
    assert any(i.type == "cross_column_mismatch" for i in issues)
    _validate_each(issues)
