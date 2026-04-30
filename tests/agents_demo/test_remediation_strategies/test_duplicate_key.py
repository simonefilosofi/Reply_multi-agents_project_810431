"""Tests for DuplicateKeyStrategy: id-column dedup + non-id flag."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.duplicate_key import DuplicateKeyStrategy
from state.issues import DuplicateKeyIssue


def test_duplicate_key_drops_dup_rows_on_id_column(make_agent) -> None:
    df = pd.DataFrame({"cf": ["A", "A", "B"], "amount": [10, 20, 30]})
    agent, working = make_agent(df, {"id_columns": ["cf"]})
    issue = DuplicateKeyIssue(column="cf", key_columns=("cf",), detail="dup", severity="medium")
    DuplicateKeyStrategy().apply(
        working, {"duplicate_key": [issue]}, agent.state.dataset_fingerprint, agent
    )
    assert len(working) == 2
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "duplicate_key"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"


def test_duplicate_key_flags_when_no_id_overlap(make_agent) -> None:
    df = pd.DataFrame({"city": ["Roma", "Roma", "Milano"], "amount": [10, 20, 30]})
    agent, working = make_agent(df, {"id_columns": []})
    issue = DuplicateKeyIssue(column="city", key_columns=("city",), detail="dup", severity="low")
    DuplicateKeyStrategy().apply(
        working, {"duplicate_key": [issue]}, agent.state.dataset_fingerprint, agent
    )
    assert len(working) == 3
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "duplicate_key"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
