"""Tests for FlagOnlyStrategy: catch-all flagging + skip-already-dropped guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.flag_only import FlagOnlyStrategy
from state.issues import DateOrderIssue, SparseColumnIssue


def test_flag_only_emits_flag_for_sparse_column(make_agent) -> None:
    df = pd.DataFrame({"sparse": [None, None, 1]})
    agent, working = make_agent(df, {})
    issue = SparseColumnIssue(column="sparse", detail="mostly empty", severity="low")
    FlagOnlyStrategy().apply(working, {"sparse_column": [issue]}, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "sparse_column"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "removal" in fix_entries[0]["description"]


def test_flag_only_skips_dropped_column(make_agent) -> None:
    df = pd.DataFrame({"present": [1]})
    agent, working = make_agent(df, {})
    issue = DateOrderIssue(
        column="dropped", column_a="dropped", column_b="other", detail="x", severity="low"
    )
    FlagOnlyStrategy().apply(working, {"date_order": [issue]}, {}, agent)
    assert agent.state.fix_log == []
