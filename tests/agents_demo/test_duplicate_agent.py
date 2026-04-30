"""Tests for DuplicateAgent typed-issue migration (Step 9).

Covers structural-field round-trips: DuplicateColumnsIssue.column_a/column_b,
DuplicateKeyIssue.key_columns, and DuplicateRowsIssue typing.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.duplicate_agent import DuplicateAgent
from state.issues import (
    ISSUE_ADAPTER,
    DuplicateColumnsIssue,
    DuplicateKeyIssue,
    IssueBase,
)
from state.pipeline_state import PipelineState


def _validate_each(issues: list[Any]) -> None:
    for issue in issues:
        assert isinstance(issue, IssueBase)
        ISSUE_ADAPTER.validate_python(issue.model_dump())


def test_duplicate_agent_typed_duplicate_rows(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"a": [1, 1, 2, 2, 3] * 4, "b": ["x", "x", "y", "y", "z"] * 4})
    state.df_raw = df
    state.dataset_fingerprint = {
        "id_columns": [],
        "suggested_key_columns": [],
        "likely_duplicate_pairs": [],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    DuplicateAgent(state).run("duplicates")

    issues = state.duplicate_report["issues"]
    assert any(i.type == "duplicate_rows" for i in issues)
    _validate_each(issues)


def test_duplicate_agent_structures_column_pair(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = pd.DataFrame({"nome": ["A", "B", "C", "D"], "name": ["A", "B", "C", "D"]})
    state.dataset_fingerprint = {
        "id_columns": [],
        "suggested_key_columns": [],
        "likely_duplicate_pairs": [["nome", "name"]],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    DuplicateAgent(state).run("duplicates")

    issues = state.duplicate_report["issues"]
    dup_cols = [i for i in issues if isinstance(i, DuplicateColumnsIssue)]
    assert dup_cols, "expected at least one DuplicateColumnsIssue"
    pair = dup_cols[0]
    assert {pair.column_a, pair.column_b} == {"nome", "name"}
    _validate_each(issues)


def test_duplicate_agent_key_collision_has_tuple_keys(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame(
        {
            "codice": ["A", "A", "B", "B", "C", "C", "D", "D", "E", "E", "F", "F"],
            "anno": [2024] * 12,
            "note": [
                "alpha",
                "beta",
                "gamma",
                "delta",
                "epsilon",
                "zeta",
                "eta",
                "theta",
                "iota",
                "kappa",
                "lambda",
                "mu",
            ],
        }
    )
    state.df_raw = df
    state.dataset_fingerprint = {
        "id_columns": [],
        "suggested_key_columns": ["codice", "anno"],
        "likely_duplicate_pairs": [],
    }
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    DuplicateAgent(state).run("duplicates")

    issues = state.duplicate_report["issues"]
    keys = [i for i in issues if isinstance(i, DuplicateKeyIssue)]
    assert keys, "expected duplicate_key issue when keys collide"
    assert keys[0].key_columns == ("codice", "anno")
    _validate_each(issues)
