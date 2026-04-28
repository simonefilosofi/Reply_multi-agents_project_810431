"""Tests for FormatPatternStrategy: typed pattern field + ID-column guard (B1 closure)."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.format_pattern import FormatPatternStrategy
from state_demo.issues import FormatPatternViolationIssue


def test_format_pattern_nulls_violations_using_typed_field(make_agent) -> None:
    df = pd.DataFrame(
        {
            "period": [
                "202401",
                "202402",
                "202403",
                "202404",
                "202405",
                "202406",
                "202407",
                "202408",
                "202409",
                "BAD",
            ]
        }
    )
    agent, working = make_agent(df, {})
    issue = FormatPatternViolationIssue(
        column="period",
        pattern=r"^\d{6}$",
        description="YYYYMM",
        detail="violations",
        severity="medium",
    )
    FormatPatternStrategy().apply(working, {"format_pattern_violation": [issue]}, {}, agent)
    assert working["period"].iloc[0] == "202401"
    assert pd.isna(working["period"].iloc[9])
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "format_pattern_violation"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"
    assert fix_entries[0]["rows_affected"] == 1


def test_format_pattern_flags_id_column(make_agent) -> None:
    df = pd.DataFrame({"cf": ["RSSMRA80A01H501U", "BAD"]})
    agent, working = make_agent(df, {"id_columns": ["cf"]})
    issue = FormatPatternViolationIssue(
        column="cf",
        pattern=r"^[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]$",
        description="CF",
        detail="violations",
        severity="high",
    )
    FormatPatternStrategy().apply(
        working, {"format_pattern_violation": [issue]}, agent.state.dataset_fingerprint, agent
    )
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "format_pattern_violation"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "ID/key column" in fix_entries[0]["description"]
