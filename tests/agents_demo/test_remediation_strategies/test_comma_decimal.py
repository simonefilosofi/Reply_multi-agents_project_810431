"""Tests for CommaDecimalStrategy (A3 closure): IT decimal conversion + flag-on-no-op."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.comma_decimal import CommaDecimalStrategy
from state.issues import CommaDecimalFormatIssue


def test_comma_decimal_converts_italian_format(make_agent) -> None:
    df = pd.DataFrame({"prezzo": ["1.234,56", "2.345,67", "3.456,78"]})
    agent, working = make_agent(df, {})
    issue = CommaDecimalFormatIssue(column="prezzo", detail="italian", severity="medium")
    CommaDecimalStrategy().apply(working, {"comma_decimal_format": [issue]}, {}, agent)
    coerced = pd.to_numeric(working["prezzo"], errors="coerce")
    assert coerced.notna().all()
    assert coerced.iloc[0] == 1234.56


def test_comma_decimal_flags_when_no_pattern_match(make_agent) -> None:
    df = pd.DataFrame({"label": ["alpha", "beta", "gamma"]})
    agent, working = make_agent(df, {})
    issue = CommaDecimalFormatIssue(column="label", detail="false positive", severity="low")
    CommaDecimalStrategy().apply(working, {"comma_decimal_format": [issue]}, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "comma_decimal_format"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
