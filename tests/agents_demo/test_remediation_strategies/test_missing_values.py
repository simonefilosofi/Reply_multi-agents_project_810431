"""Tests for MissingValuesStrategy: low-severity numeric impute + binary-flag guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.missing_values import MissingValuesStrategy
from state.issues import MissingValuesIssue


def test_missing_values_imputes_low_severity_numeric(make_agent) -> None:
    df = pd.DataFrame({"score": [10.0, 20.0, None, 40.0, 30.0]})
    agent, working = make_agent(df, {"numerical_columns": ["score"]})
    issue = MissingValuesIssue(column="score", detail="1 missing", severity="low")
    MissingValuesStrategy().apply(
        working, {"missing_values": [issue]}, agent.state.dataset_fingerprint, agent
    )
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "missing_values"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"
    assert working["score"].notna().all()


def test_missing_values_high_severity_numeric_is_flagged(make_agent) -> None:
    df = pd.DataFrame({"score": [10.0, 20.0, None, None, 30.0]})
    agent, working = make_agent(df, {"numerical_columns": ["score"]})
    issue = MissingValuesIssue(column="score", detail="lots missing", severity="high")
    MissingValuesStrategy().apply(
        working, {"missing_values": [issue]}, agent.state.dataset_fingerprint, agent
    )
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "missing_values"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"


def test_missing_values_binary_column_is_flagged(make_agent) -> None:
    df = pd.DataFrame({"flag": [0, 1, 0, None, 1]})
    agent, working = make_agent(df, {"numerical_columns": ["flag"]})
    issue = MissingValuesIssue(column="flag", detail="1 missing", severity="low")
    MissingValuesStrategy().apply(
        working, {"missing_values": [issue]}, agent.state.dataset_fingerprint, agent
    )
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "missing_values"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "Binary flag column" in fix_entries[0]["description"]
