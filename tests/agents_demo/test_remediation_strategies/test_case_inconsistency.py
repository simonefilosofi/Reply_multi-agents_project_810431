"""Tests for CaseInconsistencyStrategy: case normalisation + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.case_inconsistency import CaseInconsistencyStrategy
from state.issues import CaseInconsistencyIssue


def test_case_inconsistency_normalises_to_dominant_variant(make_agent) -> None:
    df = pd.DataFrame({"city": ["Milano", "Milano", "milano", "MILANO", "Milano"]})
    agent, working = make_agent(df, {})
    issue = CaseInconsistencyIssue(column="city", detail="mixed", severity="low")
    CaseInconsistencyStrategy().apply(working, {"case_inconsistency": [issue]}, {}, agent)
    assert (working["city"] == "Milano").all()


def test_case_inconsistency_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"other": ["x"]})
    agent, working = make_agent(df, {})
    issue = CaseInconsistencyIssue(column="city", detail="x", severity="low")
    CaseInconsistencyStrategy().apply(working, {"case_inconsistency": [issue]}, {}, agent)
    assert agent.state.fix_log == []
