"""Tests for NamingConventionStrategy: rename + skip-already-dropped guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.naming_convention import NamingConventionStrategy
from state.issues import NamingConventionIssue


def test_naming_convention_renames_camel_case(make_agent) -> None:
    df = pd.DataFrame({"CodiceFiscale": ["A", "B"]})
    agent, working = make_agent(df, {})
    issue = NamingConventionIssue(column="CodiceFiscale", detail="camel", severity="low")
    NamingConventionStrategy().apply(working, {"naming_convention": [issue]}, {}, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "naming_convention"]
    assert fix_entries
    assert fix_entries[0]["metadata"]["new"] != fix_entries[0]["metadata"]["old"]
    assert fix_entries[0]["metadata"]["new"] in working.columns


def test_naming_convention_skips_dropped_column(make_agent) -> None:
    df = pd.DataFrame({"present": [1]})
    agent, working = make_agent(df, {})
    issue = NamingConventionIssue(column="DroppedColumn", detail="x", severity="low")
    NamingConventionStrategy().apply(working, {"naming_convention": [issue]}, {}, agent)
    assert agent.state.fix_log == []
