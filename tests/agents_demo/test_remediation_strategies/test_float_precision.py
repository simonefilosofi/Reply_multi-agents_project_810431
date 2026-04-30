"""Tests for FloatPrecisionStrategy: rounding + missing-column guard."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.float_precision import FloatPrecisionStrategy
from state.issues import FloatPrecisionNoiseIssue


def test_float_precision_rounds_noise(make_agent) -> None:
    df = pd.DataFrame({"x": [1.000000001, 2.500000003, 3.0, 4.999999998]})
    agent, working = make_agent(df, {})
    issue = FloatPrecisionNoiseIssue(column="x", detail="noise", severity="low")
    FloatPrecisionStrategy().apply(working, {"float_precision_noise": [issue]}, {}, agent)
    assert working["x"].iloc[0] == 1.00
    assert working["x"].iloc[1] == 2.50


def test_float_precision_skips_missing_column(make_agent) -> None:
    df = pd.DataFrame({"y": [1.0]})
    agent, working = make_agent(df, {})
    issue = FloatPrecisionNoiseIssue(column="x", detail="x", severity="low")
    FloatPrecisionStrategy().apply(working, {"float_precision_noise": [issue]}, {}, agent)
    assert agent.state.fix_log == []
