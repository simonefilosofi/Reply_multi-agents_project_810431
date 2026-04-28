"""Tests for MixedTypeStrategy: numeric coercion + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.mixed_type import MixedTypeStrategy
from state_demo.issues import MixedTypeIssue


def test_mixed_type_coerces_to_numeric(make_agent) -> None:
    df = pd.DataFrame({"x": ["1", "2", "abc", "4"]})
    agent, working = make_agent(df, {})
    issue = MixedTypeIssue(column="x", detail="mixed", severity="medium")
    MixedTypeStrategy().apply(working, {"mixed_type": [issue]}, {}, agent)
    coerced = pd.to_numeric(working["x"], errors="coerce")
    assert coerced.iloc[0] == 1.0
    assert pd.isna(coerced.iloc[2])


def test_mixed_type_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"y": [1, 2]})
    agent, working = make_agent(df, {})
    issue = MixedTypeIssue(column="x", detail="x", severity="low")
    MixedTypeStrategy().apply(working, {"mixed_type": [issue]}, {}, agent)
    assert agent.state.fix_log == []
