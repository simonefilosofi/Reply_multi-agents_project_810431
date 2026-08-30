"""The shared PipelineState every node reads and returns an updated copy of. Fields are grouped below by the stage that fills them: input, baseline, profiling, semantic payload, duplicate-column resolution, format validation, anomaly detection, remediation proposals and approvals, the cell-level audit trail, and the measurements the report is built from. The dataset is held as Any because Pydantic cannot serialise a DataFrame."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from models import AnomalyReport, BaselineFile, ColumnPayload, DuplicateResolution, FixProposal, ImputationHint, ValidationReport


class PipelineState(BaseModel):
    dataset: Any = None
    dataset_path: str = ""

    baseline: BaselineFile | None = None
    baseline_path: str = "baseline.json"

    detected_domain: str = ""
    detected_language: str = ""

    payload: list[ColumnPayload] = Field(default_factory=list)

    surviving_columns: list[str] = Field(default_factory=list)
    duplicate_resolutions: list[DuplicateResolution] = Field(default_factory=list)

    validation_reports: list[ValidationReport] = Field(default_factory=list)
    value_corrections: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    inferred_format_specs: dict[str, dict] = Field(default_factory=dict)
    imputation_hints: dict[str, ImputationHint] = Field(default_factory=dict)

    anomaly_reports: list[AnomalyReport] = Field(default_factory=list)

    proposed_fixes: list[FixProposal] = Field(default_factory=list)
    fix_groups: dict[str, list[str]] = Field(default_factory=dict)
    approved_fix_ids: list[str] = Field(default_factory=list)
    applied_fix_ids: list[str] = Field(default_factory=list)
    auto_remediations: list[dict] = Field(default_factory=list)
    generated_function_runs: list[dict] = Field(default_factory=list)

    change_log: list[dict] = Field(default_factory=list)

    duplicate_rows: dict = Field(default_factory=dict)
    completeness: dict = Field(default_factory=dict)
    reliability: dict = Field(default_factory=dict)
    quality_snapshots: dict[str, dict] = Field(default_factory=dict)

    errors: list[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
