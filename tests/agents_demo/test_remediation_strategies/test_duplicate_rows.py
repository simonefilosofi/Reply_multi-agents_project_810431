"""Tests for DuplicateRowsStrategy: dedup + no-op when no issue."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.duplicate_rows import DuplicateRowsStrategy
from state.issues import DuplicateRowsIssue


def test_duplicate_rows_drops_duplicates(make_agent) -> None:
    df = pd.DataFrame({"a": [1, 1, 2, 3, 3], "b": ["x", "x", "y", "z", "z"]})
    agent, working = make_agent(df, {})
    issue = DuplicateRowsIssue(column="_rows_", detail="2 dups", severity="medium")
    DuplicateRowsStrategy().apply(working, {"duplicate_rows": [issue]}, {}, agent)
    assert len(working) == 3
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "duplicate_rows"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"


def test_duplicate_rows_noop_without_issue(make_agent) -> None:
    df = pd.DataFrame({"a": [1, 1, 2]})
    agent, working = make_agent(df, {})
    DuplicateRowsStrategy().apply(working, {}, {}, agent)
    assert len(working) == 3
    assert agent.state.fix_log == []
