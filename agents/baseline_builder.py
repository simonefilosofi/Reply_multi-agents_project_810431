"""Loads noipa_schema_registry.json, resolves $refs against shared_column_definitions, validates the resolved structure into BaselineFile, and writes baseline.json. Also records the "raw" quality snapshot, the apparent state of the dataset before any placeholder is unmasked. Implements the Baseline Builder agent node."""
from __future__ import annotations

import json
from pathlib import Path

from models import (
    BaselineFile,
    ColumnSchema,
    DatasetSchema,
    DomainBaseline,
    EnumFormat,
    GlobalConventions,
    RangeFormat,
    RegexFormat,
)
from state import PipelineState
from tools.duplicate_rows import duplicate_row_analysis
from tools.reliability_score import compute_metrics


_REGISTRY_PATH = Path("noipa_schema_registry.json")
_BASELINE_OUTPUT = Path("baseline.json")
_REF_PREFIX = "#/shared_column_definitions/"


def baseline_builder_node(state: PipelineState) -> PipelineState:
    baseline = _load_registry(_REGISTRY_PATH)
    _BASELINE_OUTPUT.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")
    update: dict = {"baseline": baseline}
    if state.dataset is not None:
        update["quality_snapshots"] = {
            **state.quality_snapshots,
            "raw": compute_metrics(
                state.dataset,
                conventions=baseline.global_conventions,
                duplicate_analysis=duplicate_row_analysis(state.dataset),
            ),
        }
    return state.model_copy(update=update)


def _load_registry(path: Path) -> BaselineFile:
    raw = json.loads(path.read_text(encoding="utf-8"))
    root = raw["NoiPA_Schema_Registry"]

    shared = {
        name: _build_column_schema(name, spec, canonical_id=name)
        for name, spec in root.get("shared_column_definitions", {}).items()
        if not name.startswith("_")
    }
    domains = {
        domain_name: _build_domain(domain_data, shared)
        for domain_name, domain_data in root.get("domains", {}).items()
    }
    metadata = root.get("metadata", {})
    conventions = GlobalConventions(**metadata.get("global_conventions", {}))
    observations = _flatten_observations(metadata.get("observations_log", {}))

    return BaselineFile(
        domains=domains,
        shared_definitions=shared,
        global_conventions=conventions,
        observations=observations,
    )


def _build_domain(data: dict, shared: dict[str, ColumnSchema]) -> DomainBaseline:
    return DomainBaseline(
        description=data.get("description", ""),
        datasets={
            ds_name: _build_dataset(ds_data, shared)
            for ds_name, ds_data in data.get("datasets", {}).items()
        },
    )


def _build_dataset(data: dict, shared: dict[str, ColumnSchema]) -> DatasetSchema:
    return DatasetSchema(
        description=data.get("description", ""),
        periodicity=data.get("_periodicity"),
        columns={
            col_name: _resolve_column(col_name, col_spec, shared)
            for col_name, col_spec in data.get("columns", {}).items()
        },
    )


def _resolve_column(name: str, spec: dict, shared: dict[str, ColumnSchema]) -> ColumnSchema:
    if "$ref" in spec:
        canonical_id = spec["$ref"].removeprefix(_REF_PREFIX)
        if canonical_id not in shared:
            raise ValueError(f"Unresolved $ref for column '{name}': {spec['$ref']}")
        ref = shared[canonical_id]
        return ref.model_copy(update={"column_name": name, "canonical_id": canonical_id})
    return _build_column_schema(name, spec, canonical_id=None)


def _build_column_schema(name: str, spec: dict, canonical_id: str | None) -> ColumnSchema:
    return ColumnSchema(
        column_name=name,
        dtype=spec.get("dtype", "object"),
        format=_build_format(spec.get("format")),
        case_convention=spec.get("case_convention"),
        is_nullable=spec.get("is_nullable", True),
        canonical_id=canonical_id,
    )


def _build_format(spec: dict | None):
    if not spec:
        return None
    kind = spec.get("type")
    if kind == "enum":
        return EnumFormat(values=spec["values"])
    if kind == "regex":
        return RegexFormat(pattern=spec["pattern"])
    if kind == "range":
        return RangeFormat(min=spec.get("min"), max=spec.get("max"))
    raise ValueError(f"Unknown format type: {kind}")


def _flatten_observations(log: dict) -> dict[str, list[str]]:
    return {key: value for key, value in log.items() if isinstance(value, list)}
