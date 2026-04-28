"""Tests for FractionalIntegersStrategy: NaN-out fractional values + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.fractional_integers import FractionalIntegersStrategy
from state_demo.issues import FractionalIntegersIssue


def test_fractional_integers_nulls_non_trivial_fractions(make_agent) -> None:
    df = pd.DataFrame({"qty": [1, 2, 1.5, 4, 2.7]})
    agent, working = make_agent(df, {})
    issue = FractionalIntegersIssue(column="qty", detail="x", severity="medium")
    FractionalIntegersStrategy().apply(working, {"fractional_integers": [issue]}, {}, agent)
    assert pd.isna(working["qty"].iloc[2])
    assert pd.isna(working["qty"].iloc[4])
    assert working["qty"].iloc[0] == 1
    assert working["qty"].iloc[1] == 2


def test_fractional_integers_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"other": [1, 2]})
    agent, working = make_agent(df, {})
    issue = FractionalIntegersIssue(column="qty", detail="x", severity="low")
    FractionalIntegersStrategy().apply(working, {"fractional_integers": [issue]}, {}, agent)
    assert agent.state.fix_log == []
