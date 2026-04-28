"""Tests for DerivedRecomputationStrategy: recompute after capping + no-op without capping."""

from __future__ import annotations

import pandas as pd

from agents_demo.remediation_strategies.derived_recomputation import DerivedRecomputationStrategy


def test_derived_recomputation_recomputes_profit_after_revenue_capped(make_agent) -> None:
    n = 30
    revenue_raw = [100.0 + i for i in range(n - 1)] + [99999.0]
    cost = [50.0 + i * 0.5 for i in range(n)]
    profit_raw = [revenue_raw[i] - cost[i] for i in range(n)]

    df_raw = pd.DataFrame({"revenue": revenue_raw, "cost": cost, "profit": profit_raw})
    agent, working = make_agent(df_raw, {})

    revenue_clean = revenue_raw.copy()
    revenue_clean[-1] = 200.0
    working["revenue"] = revenue_clean

    agent.state.fix_log.append(
        {
            "issue_type": "outliers",
            "column": "revenue",
            "action": "auto_fixed",
            "description": "capped",
            "rows_affected": 1,
        }
    )

    DerivedRecomputationStrategy().apply(working, {}, {}, agent)
    assert working["profit"].iloc[-1] == working["revenue"].iloc[-1] - working["cost"].iloc[-1]
    fix_entries = [
        f for f in agent.state.fix_log if f["issue_type"] == "derived_column_recomputation"
    ]
    assert fix_entries and fix_entries[0]["column"] == "profit"


def test_derived_recomputation_noop_when_no_columns_capped(make_agent) -> None:
    df = pd.DataFrame({"revenue": [100.0, 200.0], "profit": [50.0, 100.0], "cost": [50.0, 100.0]})
    agent, working = make_agent(df, {})
    DerivedRecomputationStrategy().apply(working, {}, {}, agent)
    assert agent.state.fix_log == []
