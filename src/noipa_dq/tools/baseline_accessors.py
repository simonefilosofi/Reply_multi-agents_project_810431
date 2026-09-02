"""Projection helpers exposing slice views of the resolved BaselineFile to each agent without leaking the full structure into LLM prompts. Consumed by the Profiler, Semantic, Duplicate-Column, NaN-Handler, and Format-Consistency agents."""
from __future__ import annotations

from noipa_dq.models import BaselineFile, ColumnSchema, GlobalConventions


def domain_signatures(baseline: BaselineFile) -> dict[str, dict[str, list[str]]]:
    return {
        domain_name: {
            ds_name: list(ds.columns.keys())
            for ds_name, ds in domain.datasets.items()
        }
        for domain_name, domain in baseline.domains.items()
    }


def column_catalog_all_domains(baseline: BaselineFile) -> dict[str, ColumnSchema]:
    catalog: dict[str, ColumnSchema] = {}
    for domain in baseline.domains.values():
        for dataset in domain.datasets.values():
            for col_name, schema in dataset.columns.items():
                catalog.setdefault(col_name, schema)
    return catalog


def find_spec_by_hint(
    baseline: BaselineFile, hint: str | None
) -> ColumnSchema | None:
    if not hint:
        return None
    if hint in baseline.shared_definitions:
        return baseline.shared_definitions[hint]
    return column_catalog_all_domains(baseline).get(hint)


def alias_index(baseline: BaselineFile) -> dict[str, str]:
    index: dict[str, str] = {}
    for domain in baseline.domains.values():
        for dataset in domain.datasets.values():
            for col_name, schema in dataset.columns.items():
                if schema.canonical_id:
                    index.setdefault(col_name, schema.canonical_id)
    return index


def global_conventions(baseline: BaselineFile) -> GlobalConventions:
    return baseline.global_conventions
