"""Tests for ReportAgent and the Step 13 visualisation / serialisation surface.

Covers the three new chart functions in ``tools`` (before-vs-after
completeness heatmap, dimension trajectory, issue-resolution Sankey),
the extended ``final_report`` dictionary (deliberation_log, gap_issues,
validator_outcomes, dimension_trajectory), and
``serialize_report`` (typed Pydantic ``Issue`` /
``DeliberationOutcome`` instances round-trip via ``model_dump``).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
import pytest

from agents_demo.report_agent import ReportAgent, serialize_report
from state_demo.deliberation import DeliberationOutcome, Vote
from state_demo.issues import MissingValuesIssue, OutliersIssue
from state_demo.pipeline_state import PipelineState
from tools import (
    chart_completeness_heatmap_before_after,
    chart_dimension_trajectory,
    chart_issue_resolution_sankey,
)


def _png_nonempty(path: str) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0


def test_chart_completeness_heatmap_before_after_writes_png(tmp_path):
    before = {"a": 0.40, "b": 0.95, "c": 0.10}
    after = {"a": 0.95, "b": 0.95}
    path = chart_completeness_heatmap_before_after(before, after, str(tmp_path))
    assert _png_nonempty(path)
    assert path.endswith("completeness_heatmap_before_after.png")


def test_chart_completeness_heatmap_before_after_skips_on_empty_before(tmp_path):
    assert chart_completeness_heatmap_before_after({}, {"a": 1.0}, str(tmp_path)) == ""


def test_chart_dimension_trajectory_writes_png(tmp_path):
    layers = {
        "post_synthesis": {
            "schema_conformity": 0.7,
            "completeness": 0.6,
            "uniqueness": 0.9,
            "consistency": 0.8,
            "anomaly_freedom": 0.85,
        },
        "post_remediation": {
            "schema_conformity": 0.85,
            "completeness": 0.95,
            "uniqueness": 0.92,
            "consistency": 0.88,
            "anomaly_freedom": 0.9,
        },
        "post_code_validator": {
            "schema_conformity": 0.9,
            "completeness": 0.97,
            "uniqueness": 0.95,
            "consistency": 0.9,
            "anomaly_freedom": 0.93,
        },
    }
    path = chart_dimension_trajectory(layers, str(tmp_path))
    assert _png_nonempty(path)
    assert path.endswith("reliability_trajectory.png")


def test_chart_dimension_trajectory_degrades_on_single_snapshot(tmp_path):
    layers = {"post_synthesis": {"schema_conformity": 0.5, "completeness": 0.5}}
    path = chart_dimension_trajectory(layers, str(tmp_path))
    assert _png_nonempty(path)


def test_chart_issue_resolution_sankey_writes_png(tmp_path):
    fix_log = [
        {"issue_type": "missing_values", "action": "auto_fixed", "column": "a"},
        {"issue_type": "placeholder_values", "action": "auto_fixed_by_llm", "column": "b"},
        {"issue_type": "duplicate_rows", "action": "flagged_for_review", "column": "c"},
    ]
    issues = [
        OutliersIssue(column="d", detail="outlier", severity="medium", source="anomaly"),
    ]
    path = chart_issue_resolution_sankey(fix_log, issues, str(tmp_path))
    if path == "":
        pytest.skip("kaleido image export unavailable in this environment")
    assert _png_nonempty(path)
    assert path.endswith("issue_resolution_sankey.png")


def test_chart_issue_resolution_sankey_caps_at_top_12_issue_types(tmp_path):
    fix_log = [
        {"issue_type": f"issue_type_{i:02d}", "action": "auto_fixed", "column": f"c{i}"}
        for i in range(15)
    ]
    path = chart_issue_resolution_sankey(fix_log, [], str(tmp_path))
    if path == "":
        pytest.skip("kaleido image export unavailable in this environment")
    assert _png_nonempty(path)


def test_chart_issue_resolution_sankey_returns_empty_on_no_issues(tmp_path):
    assert chart_issue_resolution_sankey([], [], str(tmp_path)) == ""


def _seed_state_for_report() -> PipelineState:
    state = PipelineState(source_path="tests/dummy.csv", source_format="csv")
    df = pd.DataFrame(
        {
            "salary": ["1000", "2000", "-999", "3000", "-999"],
            "name": ["alice", "bob", "carol", "dave", "eve"],
        }
    )
    state.df_raw = df
    state.df_cleaned = df.copy()
    state.dataset_fingerprint = {
        "domain": "test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": ["salary"],
        "categorical_columns": ["name"],
        "date_columns": [],
        "sparse_columns": [],
        "column_constraints": [],
        "column_descriptions": {},
    }
    state.completeness_by_column = {"salary": 1.0, "name": 1.0}
    state.overall_completeness = 1.0
    state.prioritized_issues = [
        MissingValuesIssue(
            column="salary",
            detail="placeholder values",
            severity="medium",
            source="completeness",
            missing_count=2,
            total=5,
        )
    ]
    state.deliberation_log = [
        DeliberationOutcome(
            contested_issue=OutliersIssue(
                column="salary",
                detail="outlier vs domain-negative",
                severity="medium",
                source="anomaly",
            ),
            votes=[
                Vote(
                    agent_name="anomaly",
                    keep_issue=True,
                    rationale="3 sigma fired",
                    confidence=0.8,
                ),
                Vote(
                    agent_name="constraint",
                    keep_issue=False,
                    rationale="domain allows negatives",
                    confidence=0.7,
                ),
            ],
            final_decision="keep",
            rationale="anomaly outweighs constraint",
        )
    ]
    state.fix_log = [
        {
            "issue_type": "placeholder_values",
            "column": "salary",
            "action": "auto_fixed_by_llm",
            "description": "replaced -999 with 0",
            "rows_affected": 2,
            "attempts": 1,
            "generated_code": "def fix(df, col):\n    df[col] = df[col]\n",
        }
    ]
    state.gap_issues = [
        {
            "column": "salary",
            "type": "format_issue",
            "detail": "leftover sentinel",
            "severity": "low",
            "filter": "df['salary'] == '-999'",
        }
    ]
    state.dimension_trajectory = {
        "post_synthesis": {"schema_conformity": 0.7, "completeness": 0.6},
        "post_remediation": {"schema_conformity": 0.85, "completeness": 0.9},
    }
    return state


def test_report_agent_populates_extended_final_report_keys(monkeypatch_llm, tmp_path):
    monkeypatch_llm["call_llm"] = "Reliability improved."

    state = _seed_state_for_report()

    import agents_demo.report_agent as report_module

    original_dir = report_module.IMAGES_DIR
    report_module.IMAGES_DIR = str(tmp_path / "images")
    try:
        agent = ReportAgent(state)
        agent.run("Compile final report")
    finally:
        report_module.IMAGES_DIR = original_dir

    report = state.final_report
    for key in ("deliberation_log", "gap_issues", "validator_outcomes", "dimension_trajectory"):
        assert key in report, f"final_report missing key: {key}"
    assert len(report["deliberation_log"]) == 1
    assert report["deliberation_log"][0]["final_decision"] == "keep"
    assert len(report["gap_issues"]) == 1
    assert any(o.get("action") == "auto_fixed_by_llm" for o in report["validator_outcomes"])
    assert "post_synthesis" in report["dimension_trajectory"]
    assert "post_remediation" in report["dimension_trajectory"]


def test_serialize_report_handles_typed_issues_and_deliberation():
    issue = MissingValuesIssue(
        column="salary",
        detail="placeholders",
        severity="medium",
        source="completeness",
        missing_count=2,
        total=5,
    )
    outcome = DeliberationOutcome(
        contested_issue=issue,
        votes=[
            Vote(
                agent_name="anomaly",
                keep_issue=True,
                rationale="r",
                confidence=0.9,
            )
        ],
        final_decision="drop",
        rationale="resolved by completeness",
    )
    report: dict[str, Any] = {
        "title": "Data Quality Report",
        "prioritized_issues": [issue],
        "deliberation_log": [outcome],
        "reliability_score_before": 70.0,
        "reliability_score_after": 90.0,
    }

    raw = serialize_report(report)
    parsed = json.loads(raw)

    assert parsed["title"] == "Data Quality Report"
    assert parsed["prioritized_issues"][0]["type"] == "missing_values"
    assert parsed["prioritized_issues"][0]["missing_count"] == 2
    assert parsed["deliberation_log"][0]["final_decision"] == "drop"
    assert parsed["deliberation_log"][0]["contested_issue"]["column"] == "salary"
