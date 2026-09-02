"""LangGraph wiring for the NoiPA data-quality pipeline: declares every agent node and the fixed edge order Ingest -> Detect -> Auto-remediate -> Propose -> Apply -> Report. Contains the graph builder and the compiled default graph."""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from noipa_dq.agents.anomaly_detector import anomaly_detector_node
from noipa_dq.agents.apply_fixes import apply_fixes_node
from noipa_dq.agents.auto_remediation import auto_remediation_node
from noipa_dq.agents.baseline_builder import baseline_builder_node
from noipa_dq.agents.duplicate_column import duplicate_column_node
from noipa_dq.agents.duplicate_row import duplicate_row_node
from noipa_dq.agents.format_consistency import format_consistency_node
from noipa_dq.agents.nan_handler import nan_handler_node
from noipa_dq.agents.profiler import profiler_node
from noipa_dq.agents.report_generator import report_generator_node
from noipa_dq.agents.semantic import semantic_node
from noipa_dq.agents.unified import unified_node
from noipa_dq.state import PipelineState

APPROVAL_GATE_NODE = "apply_fixes"


def build_graph() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("baseline_builder", baseline_builder_node)
    g.add_node("profiler", profiler_node)
    g.add_node("semantic", semantic_node)
    g.add_node("nan_handler", nan_handler_node)
    g.add_node("duplicate_column", duplicate_column_node)
    g.add_node("format_consistency", format_consistency_node)
    g.add_node("auto_remediation", auto_remediation_node)
    g.add_node("anomaly_detector", anomaly_detector_node)
    g.add_node("unified", unified_node)
    g.add_node(APPROVAL_GATE_NODE, apply_fixes_node)
    g.add_node("duplicate_row", duplicate_row_node)
    g.add_node("report_generator", report_generator_node)

    g.set_entry_point("baseline_builder")
    g.add_edge("baseline_builder", "profiler")
    g.add_edge("profiler", "semantic")
    g.add_edge("semantic", "nan_handler")
    g.add_edge("nan_handler", "duplicate_column")
    g.add_edge("duplicate_column", "format_consistency")
    g.add_edge("format_consistency", "auto_remediation")
    g.add_edge("auto_remediation", "anomaly_detector")
    g.add_edge("anomaly_detector", "unified")
    g.add_edge("unified", APPROVAL_GATE_NODE)
    g.add_edge(APPROVAL_GATE_NODE, "duplicate_row")
    g.add_edge("duplicate_row", "report_generator")
    g.add_edge("report_generator", END)

    return g


graph = build_graph().compile()
