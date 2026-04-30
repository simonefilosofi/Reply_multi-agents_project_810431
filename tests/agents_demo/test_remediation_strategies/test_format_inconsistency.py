"""Tests for FormatInconsistencyStrategy: date-format standardisation + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.format_inconsistency import FormatInconsistencyStrategy
from state.issues import FormatInconsistencyIssue


def test_format_inconsistency_standardises_mixed_dates(make_agent) -> None:
    df = pd.DataFrame({"data": ["2024-01-15", "15/02/2024", "2024-03-15", "20/04/2024"]})
    agent, working = make_agent(df, {})
    issue = FormatInconsistencyIssue(column="data", detail="mixed", severity="medium")
    FormatInconsistencyStrategy().apply(working, {"format_inconsistency": [issue]}, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "format_inconsistency"]
    assert fix_entries
    assert fix_entries[0]["action"] in ("auto_fixed", "flagged_for_review")


def test_format_inconsistency_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"other": ["2024-01-15"]})
    agent, working = make_agent(df, {})
    issue = FormatInconsistencyIssue(column="data", detail="x", severity="low")
    FormatInconsistencyStrategy().apply(working, {"format_inconsistency": [issue]}, {}, agent)
    assert agent.state.fix_log == []
