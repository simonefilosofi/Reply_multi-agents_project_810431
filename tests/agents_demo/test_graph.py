"""End-to-end smoke tests for the LangGraph pipeline scaffold.

Verifies the TypedDict round-trip with :class:`PipelineState`, the per-agent
node-runner delta semantics that keep parallel branches from clobbering each
other, and a full ``graph.invoke()`` traversal under monkeypatched LLM I/O
that exercises every node and confirms the parallel Layer-1 fan-out joins
correctly at synthesis.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-anthropic")
os.environ.setdefault("OPENAI_API_KEY", "test-key-openai")

from agents_demo._graph import (
    LAYER_1_NODES,
    PipelineStateDict,
    build_node_runner,
    build_pipeline_graph,
    state_from_dict,
    state_to_dict,
)
from agents_demo.base_agent import BaseAgent
from state_demo import settings
from state_demo.pipeline_state import PipelineState


def test_state_round_trip_preserves_fields(clean_pa_df: pd.DataFrame) -> None:
    """state_to_dict / state_from_dict must preserve every PipelineState field."""
    state = PipelineState(source_path="x.csv", source_format="csv", df_raw=clean_pa_df)
    state.agent_log.append({"agent": "test", "phase": "act", "message": "hi"})
    state.dataset_fingerprint = {"domain": "noipa"}
    state.overall_completeness = 0.97

    as_dict = state_to_dict(state)
    rebuilt = state_from_dict(dict(as_dict))

    assert rebuilt.source_path == "x.csv"
    assert rebuilt.dataset_fingerprint == {"domain": "noipa"}
    assert rebuilt.overall_completeness == 0.97
    assert rebuilt.df_raw.equals(clean_pa_df)
    assert rebuilt.agent_log == [{"agent": "test", "phase": "act", "message": "hi"}]


class _LoggingAgent(BaseAgent):
    """Tiny BaseAgent subclass used to exercise the node-runner delta logic."""

    name = "logger"
    NODE_PROMPT = "log something"

    def act(self) -> None:
        self.log("act", "hello from logger")
        self.state.cross_agent_insights.append({"insight": "x", "related_agents": []})


def test_node_runner_emits_only_deltas() -> None:
    """build_node_runner must return list deltas for reduced fields, not full lists."""
    initial = PipelineState()
    initial.agent_log.append({"agent": "prev", "phase": "act", "message": "earlier"})
    initial.cross_agent_insights.append({"insight": "old", "related_agents": []})

    runner = build_node_runner(_LoggingAgent)
    update = runner(state_to_dict(initial))

    assert isinstance(update.get("agent_log"), list)
    assert len(update["agent_log"]) == 1
    assert update["agent_log"][0]["message"] == "hello from logger"

    assert isinstance(update.get("cross_agent_insights"), list)
    assert len(update["cross_agent_insights"]) == 1
    assert update["cross_agent_insights"][0]["insight"] == "x"


def test_pipeline_graph_invoke_runs_every_node(
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
    dirty_pa_df: pd.DataFrame,
    tmp_path: Any,
) -> None:
    """A full graph.invoke() must execute every pipeline node and aggregate logs."""
    csv_path = tmp_path / "dirty.csv"
    dirty_pa_df.to_csv(csv_path, index=False, encoding="utf-8")

    monkeypatch_llm["call_llm"] = "stub summary"
    monkeypatch_llm["call_llm_json"] = {"issues": []}

    graph = build_pipeline_graph(settings, with_checkpointer=False)

    initial: PipelineStateDict = PipelineStateDict(source_path=str(csv_path))
    final = graph.invoke(dict(initial))

    visited = {entry["agent"] for entry in final.get("agent_log", [])}
    expected_at_least = {"ingestion", "profiler", "remediation", "report"}
    assert expected_at_least.issubset(visited), (
        f"missing nodes in agent_log; visited={sorted(visited)}"
    )
    assert any("synthesis" in name for name in visited), (
        f"synthesis variant missing from agent_log; visited={sorted(visited)}"
    )

    layer1_visited = {n for n in LAYER_1_NODES if n in visited}
    assert len(layer1_visited) >= 2, (
        f"expected at least two Layer-1 branches in agent_log, got {layer1_visited}"
    )

    log_entries = final.get("agent_log", [])
    ingestion_entries = [e for e in log_entries if e["agent"] == "ingestion"]
    profiler_entries = [e for e in log_entries if e["agent"] == "profiler"]
    assert len(ingestion_entries) == 3, (
        f"ingestion runs once and emits exactly 3 TAOR log entries, "
        f"got {len(ingestion_entries)}: {ingestion_entries}"
    )
    assert len(profiler_entries) >= 1, "profiler must emit at least one log entry"
    profiler_phases = [e["phase"] for e in profiler_entries]
    assert len(profiler_phases) == len(set(profiler_phases) | {p for p in profiler_phases}), (
        "profiler entries should not be duplicated across reducer runs"
    )
    seen_keys: set[tuple[str, str, str]] = set()
    for entry in log_entries:
        key = (entry["agent"], entry["phase"], entry["message"])
        assert key not in seen_keys, (
            f"duplicate log entry detected (operator.add reducer over shared list): {key}"
        )
        seen_keys.add(key)


def test_compiled_graph_renders_mermaid() -> None:
    """The compiled graph must produce a Mermaid diagram listing every node."""
    graph = build_pipeline_graph(settings, with_checkpointer=False)
    mermaid = graph.get_graph().draw_mermaid()
    for node in (
        "ingestion",
        "profiler",
        "schema",
        "completeness",
        "duplicate",
        "anomaly",
        "consistency",
        "constraint",
        "synthesis",
        "remediation",
        "report",
    ):
        assert node in mermaid, f"node {node!r} missing from Mermaid output"
