"""Tests for LookupImputationStrategy: cross-column mapping fill + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.lookup_imputation import LookupImputationStrategy
from state_demo.issues import LookupImputabilityIssue


def test_lookup_imputation_fills_via_learned_mapping(make_agent) -> None:
    df = pd.DataFrame(
        {
            "code": ["RM", "MI", "RM", "MI", "RM"],
            "city": ["Roma", "Milano", "Roma", None, None],
        }
    )
    agent, working = make_agent(df, {})
    issue = LookupImputabilityIssue(
        column="city", mapping_source="code", detail="x", severity="medium"
    )
    LookupImputationStrategy().apply(working, {"lookup_imputability": [issue]}, {}, agent)
    assert working["city"].iloc[3] == "Milano"
    assert working["city"].iloc[4] == "Roma"


def test_lookup_imputation_skips_when_source_missing(make_agent) -> None:
    df = pd.DataFrame({"city": ["Roma", None]})
    agent, working = make_agent(df, {})
    issue = LookupImputabilityIssue(
        column="city", mapping_source="code", detail="x", severity="low"
    )
    LookupImputationStrategy().apply(working, {"lookup_imputability": [issue]}, {}, agent)
    assert agent.state.fix_log == []
