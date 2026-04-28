"""Shared fixtures for the per-strategy test suite (Step 11 validation).

Strategies are exercised in isolation by:
  * seeding ``state.df_raw`` and ``state.dataset_fingerprint``;
  * instantiating a :class:`RemediationAgent` so the strategy can call
    ``agent.log_fix`` and (for ``MissingValuesStrategy``) ``ask_llm_strategy``;
  * invoking ``Strategy().apply(df, issues_by_type, fp, agent)`` directly so
    the test sees only the slice of behaviour under examination.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from agents_demo.remediation_agent import RemediationAgent
from state_demo.pipeline_state import PipelineState


def make_fp(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "domain": "test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": [],
        "categorical_columns": [],
        "date_columns": [],
        "sparse_columns": [],
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    base.update(overrides)
    return base


@pytest.fixture
def make_agent() -> Any:
    def _factory(df: pd.DataFrame, fp: dict[str, Any]) -> tuple[RemediationAgent, pd.DataFrame]:
        state = PipelineState()
        state.df_raw = df
        state.dataset_fingerprint = fp
        agent = RemediationAgent(state)
        return agent, df.copy()

    return _factory
