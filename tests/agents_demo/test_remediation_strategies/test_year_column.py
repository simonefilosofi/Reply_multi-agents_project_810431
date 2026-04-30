"""Tests for YearColumnStrategy: trailing-noise + 2-digit expansion + per-column dedup."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.year_column import YearColumnStrategy
from state.issues import AmbiguousYearFormatIssue, YearFormatInconsistencyIssue


def test_year_column_strips_noise(make_agent) -> None:
    df = pd.DataFrame({"anno": ["2024", "2024 ", "2024X", "2024"]})
    agent, working = make_agent(df, {})
    issue = YearFormatInconsistencyIssue(column="anno", detail="dirty", severity="medium")
    YearColumnStrategy().apply(working, {"year_format_inconsistency": [issue]}, {}, agent)
    coerced = pd.to_numeric(working["anno"], errors="coerce")
    assert (coerced == 2024).all()


def test_year_column_dedups_two_issue_types_per_column(make_agent) -> None:
    df = pd.DataFrame({"anno": ["24", "25", "26"]})
    agent, working = make_agent(df, {})
    issues = {
        "year_format_inconsistency": [
            YearFormatInconsistencyIssue(column="anno", detail="x", severity="low")
        ],
        "ambiguous_year_format": [
            AmbiguousYearFormatIssue(column="anno", detail="x", severity="low")
        ],
    }
    YearColumnStrategy().apply(working, issues, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["column"] == "anno"]
    assert len(fix_entries) == 1
