"""Tests for InvalidDatesStrategy: date re-parse + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.invalid_dates import InvalidDatesStrategy
from state_demo.issues import InvalidDatesIssue


def test_invalid_dates_reparses_italian_dates(make_agent) -> None:
    df = pd.DataFrame({"data": ["15/01/2024", "20/02/2024", "31/12/2024"]})
    agent, working = make_agent(df, {})
    issue = InvalidDatesIssue(column="data", detail="dirty", severity="medium")
    InvalidDatesStrategy().apply(working, {"invalid_dates": [issue]}, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "invalid_dates"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"


def test_invalid_dates_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"other": [1, 2]})
    agent, working = make_agent(df, {})
    issue = InvalidDatesIssue(column="data", detail="x", severity="low")
    InvalidDatesStrategy().apply(working, {"invalid_dates": [issue]}, {}, agent)
    assert agent.state.fix_log == []
