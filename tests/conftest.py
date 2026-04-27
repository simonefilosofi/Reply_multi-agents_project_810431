"""Pytest fixtures shared across the NoiPA pipeline test suite.

Provides:
    - ``clean_pa_df`` / ``dirty_pa_df`` / ``wide_dirty_df``: synthetic
      DataFrame fixtures built by ``data/examples/_generate.py`` and seeded
      with ``numpy.random.default_rng(seed=42)`` for byte-stable reuse.
    - ``state``: a fresh ``PipelineState`` per test so detector mutations
      cannot leak across tests.
    - ``monkeypatch_llm``: replaces ``BaseAgent.call_llm`` and
      ``BaseAgent.call_llm_json`` with deterministic stubs so unit tests
      never spend real LLM credits. Returns a mutable ``canned`` dict the
      test can use to override the stub responses per call.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data" / "examples"))

from _generate import (  # noqa: E402
    build_clean_pa_df,
    build_dirty_pa_df,
    build_large_synthetic_df,
    build_wide_dirty_df,
)

from state_demo.pipeline_state import PipelineState  # noqa: E402


@pytest.fixture
def clean_pa_df() -> pd.DataFrame:
    """Minimal canonical NoiPA-style payroll slice (~120 rows)."""
    return build_clean_pa_df()


@pytest.fixture
def dirty_pa_df() -> pd.DataFrame:
    """500-row dirty NoiPA dataframe with every detector-firing pattern injected."""
    return build_dirty_pa_df()


@pytest.fixture
def wide_dirty_df() -> pd.DataFrame:
    """30-column dataset exercising sparse, duplicate, conditional and lookup patterns."""
    return build_wide_dirty_df()


@pytest.fixture
def large_synthetic_df() -> pd.DataFrame:
    """5000-row scale-up of the dirty schema for performance smoke tests."""
    return build_large_synthetic_df()


@pytest.fixture
def state() -> PipelineState:
    """Fresh PipelineState per test."""
    return PipelineState()


@pytest.fixture
def monkeypatch_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace BaseAgent.call_llm and call_llm_json with deterministic stubs.

    Returns a mutable ``canned`` dict the test can mutate to override the
    return value per call::

        def test_something(monkeypatch_llm):
            monkeypatch_llm["call_llm"] = "stub summary"
            monkeypatch_llm["call_llm_json"] = [{"type": "missing_values", ...}]
    """
    from agents_demo.base_agent import BaseAgent

    canned: dict[str, Any] = {"call_llm": "", "call_llm_json": []}

    def _fake_call_llm(self: BaseAgent, user: str, max_tokens: int = 4096) -> str:
        return str(canned["call_llm"])

    def _fake_call_llm_json(
        self: BaseAgent,
        user: str,
        max_tokens: int = 4096,
        required_keys: list[str] | None = None,
    ) -> Any:
        return canned["call_llm_json"]

    monkeypatch.setattr(BaseAgent, "call_llm", _fake_call_llm)
    monkeypatch.setattr(BaseAgent, "call_llm_json", _fake_call_llm_json)
    return canned
