"""Scrapes PA open-data portal, clusters datasets by domain, builds baseline.json."""
from __future__ import annotations

from state import PipelineState
from tools.cluster_by_domain import cluster_by_domain
from tools.extract_column_schema import extract_column_schema
from tools.scrape_pa_datasets import scrape_pa_datasets


def baseline_builder_node(state: PipelineState) -> PipelineState:
    datasets = scrape_pa_datasets()
    clustered = cluster_by_domain(datasets)
    baseline = extract_column_schema(clustered)
    return state.model_copy(update={"baseline": baseline})
