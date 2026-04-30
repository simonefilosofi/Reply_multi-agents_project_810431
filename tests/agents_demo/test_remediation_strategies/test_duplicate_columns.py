"""Tests for DuplicateColumnsStrategy: drop-after-jaccard guard + complementary skip."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.duplicate_columns import DuplicateColumnsStrategy
from state.issues import DuplicateColumnsIssue


def test_duplicate_columns_drops_one_when_overlap_high(make_agent) -> None:
    df = pd.DataFrame(
        {"city": ["Roma", "Milano", "Torino"], "city_v2": ["Roma", "Milano", "Torino"]}
    )
    agent, working = make_agent(df, {})
    issue = DuplicateColumnsIssue(
        column="city/city_v2", column_a="city", column_b="city_v2", detail="dup", severity="medium"
    )
    DuplicateColumnsStrategy().apply(working, {"duplicate_columns": [issue]}, {}, agent)
    assert "city" in working.columns or "city_v2" in working.columns
    assert len(working.columns) == 1
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "duplicate_columns"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"


def test_duplicate_columns_flags_complementary_pair(make_agent) -> None:
    df = pd.DataFrame(
        {
            "code": ["RM", "MI", "TO", "BO", "FI"],
            "name": ["Roma", "Milano", "Torino", "Bologna", "Firenze"],
        }
    )
    agent, working = make_agent(df, {})
    issue = DuplicateColumnsIssue(
        column="code/name", column_a="code", column_b="name", detail="dup?", severity="low"
    )
    DuplicateColumnsStrategy().apply(working, {"duplicate_columns": [issue]}, {}, agent)
    assert set(working.columns) == {"code", "name"}
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "duplicate_columns"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "complementary" in fix_entries[0]["description"]
