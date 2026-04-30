"""Projection helpers exposing slice views of the resolved BaselineFile to each agent without leaking the full structure into LLM prompts. Consumed by the Profiler, Semantic, Duplicate-Column, NaN-Handler, and Format-Consistency agents."""
from __future__ import annotations

from models import BaselineFile, ColumnSchema, GlobalConventions


def domain_signatures(baseline: BaselineFile) -> dict[str, dict[str, list[str]]]:
    return {
        domain_name: {
            ds_name: list(ds.columns.keys())
            for ds_name, ds in domain.datasets.items()
        }
        for domain_name, domain in baseline.domains.items()
    }


def column_catalog_for_dataset(
    baseline: BaselineFile, domain: str, dataset: str
) -> dict[str, ColumnSchema]:
    domain_obj = baseline.domains.get(domain)
    if domain_obj is None:
        return {}
    dataset_obj = domain_obj.datasets.get(dataset)
    if dataset_obj is None:
        return {}
    return dict(dataset_obj.columns)


def column_catalog_for_domain(
    baseline: BaselineFile, domain: str
) -> dict[str, ColumnSchema]:
    domain_obj = baseline.domains.get(domain)
    if domain_obj is None:
        return {}
    catalog: dict[str, ColumnSchema] = {}
    for dataset in domain_obj.datasets.values():
        for col_name, schema in dataset.columns.items():
            catalog.setdefault(col_name, schema)
    return catalog


def find_spec_by_hint(
    baseline: BaselineFile, domain: str, hint: str | None
) -> ColumnSchema | None:
    if not hint:
        return None
    if hint in baseline.shared_definitions:
        return baseline.shared_definitions[hint]
    return column_catalog_for_domain(baseline, domain).get(hint)


def alias_index(baseline: BaselineFile) -> dict[str, str]:
    index: dict[str, str] = {}
    for domain in baseline.domains.values():
        for dataset in domain.datasets.values():
            for col_name, schema in dataset.columns.items():
                if schema.canonical_id:
                    index.setdefault(col_name, schema.canonical_id)
    return index


def format_spec(
    baseline: BaselineFile, domain: str, dataset: str, column: str
):
    schema = column_catalog_for_dataset(baseline, domain, dataset).get(column)
    return schema.format if schema else None


def observations_for(baseline: BaselineFile, domain: str) -> list[str]:
    key = f"{domain.lower()}_observations"
    return baseline.observations.get(key, [])


def global_conventions(baseline: BaselineFile) -> GlobalConventions:
    return baseline.global_conventions
