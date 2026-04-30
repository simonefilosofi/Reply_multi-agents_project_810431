"""Tests for PlaceholderStrategy: NULL conversion + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.placeholder import PlaceholderStrategy
from state.issues import PlaceholderValuesIssue


def test_placeholder_replaces_known_sentinels(make_agent) -> None:
    df = pd.DataFrame({"city": ["Roma", "n.d.", "da verificare", "Milano"]})
    agent, working = make_agent(df, {})
    issue = PlaceholderValuesIssue(column="city", detail="placeholders", severity="medium")
    PlaceholderStrategy().apply(working, {"placeholder_values": [issue]}, {}, agent)
    assert pd.isna(working["city"].iloc[1])
    assert pd.isna(working["city"].iloc[2])
    assert working["city"].iloc[0] == "Roma"


def test_placeholder_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"other": [1, 2]})
    agent, working = make_agent(df, {})
    issue = PlaceholderValuesIssue(column="city", detail="x", severity="low")
    PlaceholderStrategy().apply(working, {"placeholder_values": [issue]}, {}, agent)
    assert agent.state.fix_log == []
