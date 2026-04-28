"""LangGraph orchestration layer for the data-quality pipeline.

Defines the TypedDict mirror of :class:`PipelineState` with reducer
annotations so parallel Layer-1 branches concatenate their ``agent_log`` and
``cross_agent_insights`` contributions instead of clobbering them, plus the
``build_node_runner`` factory that adapts a TAOR :class:`BaseAgent` subclass
into a LangGraph node function returning only the deltas the agent produced.

``build_pipeline_graph`` compiles the full pipeline: Layer 0 ingestion and
profiler, Layer 1 detectors fanned out in parallel from profiler and joined
at synthesis, then remediation (which from Step 11 onward enqueues residual
issues into ``state.gap_issues``), an optional code-validator branch that
fires when ``gap_issues`` is non-empty AND the toggle is on (the validator
node itself is refactored to read from ``state.gap_issues`` in Step 12),
and the final report node.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from state_demo.config import Settings
from state_demo.pipeline_state import PipelineState

LAYER_1_NODES: tuple[str, ...] = (
    "schema",
    "completeness",
    "duplicate",
    "anomaly",
    "consistency",
    "constraint",
)


class PipelineStateDict(TypedDict, total=False):
    """LangGraph state schema mirroring :class:`PipelineState`.

    Fields written by multiple parallel branches use ``operator.add`` reducers;
    every other field uses LangGraph's default last-writer-wins semantics.
    """

    source_path: str
    source_format: str
    df_raw: pd.DataFrame
    ingestion_meta: dict[str, Any]
    dataset_fingerprint: dict[str, Any]
    agent_log: Annotated[list[dict[str, Any]], operator.add]
    cross_agent_insights: Annotated[list[dict[str, Any]], operator.add]
    completeness_by_column: dict[str, Any]
    overall_completeness: float
    schema_report: dict[str, Any]
    completeness_report: dict[str, Any]
    duplicate_report: dict[str, Any]
    anomaly_report: dict[str, Any]
    consistency_report: dict[str, Any]
    constraint_report: dict[str, Any]
    schema_summary: str
    completeness_summary: str
    duplicate_summary: str
    anomaly_summary: str
    consistency_summary: str
    constraint_summary: str
    prioritized_issues: list[Any]
    deliberation_log: list[Any]
    synthesis_summary: str
    remediation_plan: list[dict[str, Any]]
    fix_log: list[dict[str, Any]]
    df_cleaned: pd.DataFrame | None
    human_review_items: list[dict[str, Any]]
    reliability_score_before: float
    reliability_score_after: float
    final_report: dict[str, Any]
    gap_issues: list[dict[str, Any]]


_REDUCED_LIST_FIELDS: frozenset[str] = frozenset({"agent_log", "cross_agent_insights"})


def state_to_dict(state: PipelineState) -> PipelineStateDict:
    """Project a :class:`PipelineState` dataclass into a plain TypedDict."""
    return PipelineStateDict(
        source_path=state.source_path,
        source_format=state.source_format,
        df_raw=state.df_raw,
        ingestion_meta=state.ingestion_meta,
        dataset_fingerprint=state.dataset_fingerprint,
        agent_log=list(state.agent_log),
        cross_agent_insights=list(state.cross_agent_insights),
        completeness_by_column=state.completeness_by_column,
        overall_completeness=state.overall_completeness,
        schema_report=state.schema_report,
        completeness_report=state.completeness_report,
        duplicate_report=state.duplicate_report,
        anomaly_report=state.anomaly_report,
        consistency_report=state.consistency_report,
        constraint_report=state.constraint_report,
        schema_summary=state.schema_summary,
        completeness_summary=state.completeness_summary,
        duplicate_summary=state.duplicate_summary,
        anomaly_summary=state.anomaly_summary,
        consistency_summary=state.consistency_summary,
        constraint_summary=state.constraint_summary,
        prioritized_issues=state.prioritized_issues,
        deliberation_log=state.deliberation_log,
        synthesis_summary=state.synthesis_summary,
        remediation_plan=state.remediation_plan,
        fix_log=state.fix_log,
        df_cleaned=state.df_cleaned,
        human_review_items=state.human_review_items,
        reliability_score_before=state.reliability_score_before,
        reliability_score_after=state.reliability_score_after,
        final_report=state.final_report,
        gap_issues=list(state.gap_issues),
    )


def state_from_dict(state_dict: PipelineStateDict | dict[str, Any]) -> PipelineState:
    """Rehydrate a :class:`PipelineState` dataclass from a LangGraph state dict.

    Reduced list fields are copied defensively so node mutations do not leak back
    into LangGraph's internal accumulator (which would double-count via the
    ``operator.add`` reducer).
    """
    state = PipelineState()
    for field_name, value in state_dict.items():
        if not hasattr(state, field_name):
            continue
        if field_name in _REDUCED_LIST_FIELDS and isinstance(value, list):
            setattr(state, field_name, list(value))
        else:
            setattr(state, field_name, value)
    return state


def _values_equal(pre: Any, post: Any) -> bool:
    if isinstance(pre, pd.DataFrame) or isinstance(post, pd.DataFrame):
        if not (isinstance(pre, pd.DataFrame) and isinstance(post, pd.DataFrame)):
            return False
        return bool(pre.equals(post))
    if pre is post:
        return True
    try:
        return bool(pre == post)
    except Exception:
        return False


def build_node_runner(cls: type) -> Callable[[PipelineStateDict], dict[str, Any]]:
    """Return a LangGraph node function that runs a TAOR agent class.

    The returned callable accepts a state dict, hydrates a
    :class:`PipelineState`, runs the agent's ``run(NODE_PROMPT)`` cycle, then
    emits only the fields the agent actually changed. Appendable lists wired
    to ``operator.add`` reducers are emitted as deltas so parallel branches
    cooperate instead of overwriting one another.
    """

    def run_node(state_dict: PipelineStateDict) -> dict[str, Any]:
        state = state_from_dict(state_dict)
        pre_log_len = len(state.agent_log)
        pre_insights_len = len(state.cross_agent_insights)
        pre_dict = state_to_dict(state)

        agent = cls(state)
        agent.run(getattr(cls, "NODE_PROMPT", "") or "")

        post_dict = state_to_dict(state)
        updates: dict[str, Any] = {}

        log_delta = state.agent_log[pre_log_len:]
        if log_delta:
            updates["agent_log"] = list(log_delta)
        insights_delta = state.cross_agent_insights[pre_insights_len:]
        if insights_delta:
            updates["cross_agent_insights"] = list(insights_delta)

        for key, post_value in post_dict.items():
            if key in _REDUCED_LIST_FIELDS:
                continue
            pre_value = pre_dict.get(key)
            if not _values_equal(pre_value, post_value):
                updates[key] = post_value
        return updates

    return run_node


def build_pipeline_graph(
    settings: Settings, *, with_checkpointer: bool = True
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Compile and return the full pipeline graph.

    Layer 1 detectors fan out from the profiler and rejoin at synthesis. The
    conditional edge after remediation routes to the code-validator when
    ``gap_issues`` is populated and the toggle is enabled, otherwise straight
    to the report node.
    """
    from agents_demo.anomaly_agent import AnomalyAgent
    from agents_demo.code_validator_agent import CodeValidatorAgent
    from agents_demo.completeness_agent import CompletenessAgent
    from agents_demo.consistency_agent import ConsistencyAgent
    from agents_demo.constraint_agent import ConstraintAgent
    from agents_demo.duplicate_agent import DuplicateAgent
    from agents_demo.ingestion_agent import IngestionAgent
    from agents_demo.profiler_agent import ProfilerAgent
    from agents_demo.remediation_agent import RemediationAgent
    from agents_demo.report_agent import ReportAgent
    from agents_demo.schema_agent import SchemaAgent
    from agents_demo.synthesis_agent import SynthesisAgent

    graph: StateGraph[Any, Any, Any, Any] = StateGraph(PipelineStateDict)

    graph.add_node("ingestion", IngestionAgent.as_node())
    graph.add_node("profiler", ProfilerAgent.as_node())
    graph.add_node("schema", SchemaAgent.as_node())
    graph.add_node("completeness", CompletenessAgent.as_node())
    graph.add_node("duplicate", DuplicateAgent.as_node())
    graph.add_node("anomaly", AnomalyAgent.as_node())
    graph.add_node("consistency", ConsistencyAgent.as_node())
    graph.add_node("constraint", ConstraintAgent.as_node())
    graph.add_node("synthesis", SynthesisAgent.as_node())
    graph.add_node("remediation", RemediationAgent.as_node())
    graph.add_node("code_validator", CodeValidatorAgent.as_node())
    graph.add_node("report", ReportAgent.as_node())

    graph.set_entry_point("ingestion")
    graph.add_edge("ingestion", "profiler")

    for layer1 in LAYER_1_NODES:
        graph.add_edge("profiler", layer1)
        graph.add_edge(layer1, "synthesis")

    graph.add_edge("synthesis", "remediation")

    def route_after_remediation(state: PipelineStateDict) -> str:
        if settings.pipeline.enable_code_validator and state.get("gap_issues"):
            return "code_validator"
        return "report"

    graph.add_conditional_edges(
        "remediation",
        route_after_remediation,
        {"code_validator": "code_validator", "report": "report"},
    )
    graph.add_edge("code_validator", "report")
    graph.add_edge("report", END)

    if not with_checkpointer:
        return graph.compile()
    if settings.pipeline.langgraph_checkpoint == "memory":
        checkpointer = MemorySaver()
    else:
        from langgraph.checkpoint.sqlite import SqliteSaver

        checkpointer = SqliteSaver.from_conn_string("checkpoints.db")
    return graph.compile(checkpointer=checkpointer)
