"""Tests for OutlierStrategy: Tukey-fence cap + ID/categorical/skew guards."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.outliers import OutlierStrategy
from state_demo.issues import OutliersIssue


def test_outliers_caps_symmetric_distribution(make_agent) -> None:
    values = [float(i) for i in range(40)] + [-160.0, 200.0]
    df = pd.DataFrame({"x": values})
    agent, working = make_agent(df, {"numerical_columns": ["x"]})
    issue = OutliersIssue(column="x", detail="symmetric tails", severity="medium")
    OutlierStrategy().apply(working, {"outliers": [issue]}, agent.state.dataset_fingerprint, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "outliers"]
    assert fix_entries and fix_entries[0]["action"] == "auto_fixed"
    assert working["x"].max() < 200.0
    assert working["x"].min() > -160.0


def test_outliers_skips_skewed_distribution(make_agent) -> None:
    values = [10.0, 11.0, 12.0, 11.5, 10.5, 11.2, 10.8, 11.3, 10.7, 11.1, 1000.0]
    df = pd.DataFrame({"x": values})
    agent, working = make_agent(df, {"numerical_columns": ["x"]})
    issue = OutliersIssue(column="x", detail="power-law tail", severity="medium")
    OutlierStrategy().apply(working, {"outliers": [issue]}, agent.state.dataset_fingerprint, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "outliers"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "Skewed distribution" in fix_entries[0]["description"]
    assert working["x"].max() == 1000.0


def test_outliers_skips_id_column(make_agent) -> None:
    df = pd.DataFrame({"id": [1, 2, 3, 9999]})
    agent, working = make_agent(df, {"id_columns": ["id"]})
    issue = OutliersIssue(column="id", detail="x", severity="medium")
    OutlierStrategy().apply(working, {"outliers": [issue]}, agent.state.dataset_fingerprint, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "outliers"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "ID/key column" in fix_entries[0]["description"]


def test_outliers_skips_categorical_column(make_agent) -> None:
    df = pd.DataFrame({"code": [1, 2, 3, 99]})
    agent, working = make_agent(df, {"categorical_columns": ["code"]})
    issue = OutliersIssue(column="code", detail="x", severity="medium")
    OutlierStrategy().apply(working, {"outliers": [issue]}, agent.state.dataset_fingerprint, agent)
    fix_entries = [f for f in agent.state.fix_log if f["issue_type"] == "outliers"]
    assert fix_entries and fix_entries[0]["action"] == "flagged_for_review"
    assert "categorical" in fix_entries[0]["description"]
