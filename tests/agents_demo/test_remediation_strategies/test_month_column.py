"""Tests for MonthColumnStrategy: text/code normalisation + per-column dedup."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.month_column import MonthColumnStrategy
from state_demo.issues import MonthFormatInconsistencyIssue, SpecialMonthCodeIssue


def test_month_column_normalises_text_and_specials(make_agent) -> None:
    df = pd.DataFrame({"mese": ["gennaio", "FEB", "13", "5"]})
    agent, working = make_agent(df, {})
    issue = MonthFormatInconsistencyIssue(column="mese", detail="mixed", severity="medium")
    MonthColumnStrategy().apply(working, {"month_format_inconsistency": [issue]}, {}, agent)
    coerced = pd.to_numeric(working["mese"], errors="coerce")
    assert coerced.iloc[0] == 1
    assert coerced.iloc[1] == 2
    assert pd.isna(coerced.iloc[2])
    assert coerced.iloc[3] == 5


def test_month_column_dedups_when_two_issues_target_same_column(make_agent) -> None:
    df = pd.DataFrame({"mese": ["gennaio", "13"]})
    agent, working = make_agent(df, {})
    issues = {
        "month_format_inconsistency": [
            MonthFormatInconsistencyIssue(column="mese", detail="x", severity="medium")
        ],
        "special_month_code": [SpecialMonthCodeIssue(column="mese", detail="x", severity="low")],
    }
    MonthColumnStrategy().apply(working, issues, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["column"] == "mese"]
    assert len(fix_entries) == 1
