from __future__ import annotations

from langgraph.graph import END, StateGraph

from agents.baseline_builder import baseline_builder_node
from agents.classification import classification_node
from agents.duplicate_column import duplicate_column_node
from agents.duplicate_row import duplicate_row_node
from agents.format_consistency import format_consistency_node
from agents.nan_handler import nan_handler_node
from agents.profiler import profiler_node
from agents.semantic import semantic_node
from state import PipelineState


def build_graph() -> StateGraph:
    g = StateGraph(PipelineState)

    g.add_node("baseline_builder", baseline_builder_node)
    g.add_node("profiler", profiler_node)
    g.add_node("semantic", semantic_node)
    g.add_node("duplicate_column", duplicate_column_node)
    g.add_node("classification", classification_node)
    g.add_node("format_consistency", format_consistency_node)
    g.add_node("nan_handler", nan_handler_node)
    g.add_node("duplicate_row", duplicate_row_node)

    g.set_entry_point("baseline_builder")
    g.add_edge("baseline_builder", "profiler")
    g.add_edge("profiler", "semantic")
    g.add_edge("semantic", "nan_handler")
    g.add_edge("nan_handler", "duplicate_column")
    g.add_edge("duplicate_column", "classification")
    g.add_edge("classification", "format_consistency")
    g.add_edge("format_consistency", "duplicate_row")
    g.add_edge("duplicate_row", END)

    return g


graph = build_graph().compile()
