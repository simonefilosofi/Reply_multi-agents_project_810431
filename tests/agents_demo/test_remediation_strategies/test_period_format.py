"""Tests for PeriodFormatStrategy: positive normalisation + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.period_format import PeriodFormatStrategy
from state_demo.issues import PeriodFormatInconsistencyIssue


def test_period_format_normalises_mixed_codes(make_agent) -> None:
    df = pd.DataFrame({"periodo": ["2024-01", "2024.02", "202403", "garbage"]})
    agent, working = make_agent(df, fp_overrides := {})
    fp = fp_overrides
    issue = PeriodFormatInconsistencyIssue(column="periodo", detail="mixed", severity="medium")
    PeriodFormatStrategy().apply(working, {"period_format_inconsistency": [issue]}, fp, agent)
    assert working["periodo"].iloc[0] == "01-2024"
    assert pd.isna(working["periodo"].iloc[1])
    assert working["periodo"].iloc[2] == "03-2024"
    assert pd.isna(working["periodo"].iloc[3])
    assert any(f["issue_type"] == "period_format_inconsistency" for f in agent.state.fix_log)


def test_period_format_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"other": [1, 2, 3]})
    agent, working = make_agent(df, {})
    issue = PeriodFormatInconsistencyIssue(column="periodo", detail="mixed", severity="low")
    PeriodFormatStrategy().apply(working, {"period_format_inconsistency": [issue]}, {}, agent)
    assert agent.state.fix_log == []
