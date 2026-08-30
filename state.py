from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
from pydantic import BaseModel, Field

from models import AnomalyReport, BaselineFile, ColumnPayload, DuplicateResolution, FixProposal, ImputationHint, ValidationReport


class PipelineState(BaseModel):
    # input
    dataset: Any = None  # pd.DataFrame — not serializable by Pydantic; held as Any
    dataset_path: str = ""

    # baseline
    baseline: BaselineFile | None = None
    baseline_path: str = "baseline.json"

    # profiling
    detected_domain: str = ""
    detected_language: str = ""

    # semantic payload (one entry per column)
    payload: list[ColumnPayload] = Field(default_factory=list)

    # after duplicate-column removal
    surviving_columns: list[str] = Field(default_factory=list)
    duplicate_resolutions: list[DuplicateResolution] = Field(default_factory=list)

    # format validation
    validation_reports: list[ValidationReport] = Field(default_factory=list)
    value_corrections: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    inferred_format_specs: dict[str, dict] = Field(default_factory=dict)
    imputation_hints: dict[str, ImputationHint] = Field(default_factory=dict)

    # anomaly detection
    anomaly_reports: list[AnomalyReport] = Field(default_factory=list)

    # remediation proposals + approvals
    proposed_fixes: list[FixProposal] = Field(default_factory=list)
    fix_groups: dict[str, list[str]] = Field(default_factory=dict)
    approved_fix_ids: list[str] = Field(default_factory=list)
    applied_fix_ids: list[str] = Field(default_factory=list)

    # corrections applied automatically because the data determines them
    auto_remediations: list[dict] = Field(default_factory=list)

    # which executor validated each generated cleaning function (sandbox or local cage)
    generated_function_runs: list[dict] = Field(default_factory=list)

    # cell-level audit trail of every applied change
    change_log: list[dict] = Field(default_factory=list)

    # duplicate-row ledger (exact removals and key collisions)
    duplicate_rows: dict = Field(default_factory=dict)

    # completeness analysis (per column, per row, dataset-wide, sparse columns)
    completeness: dict = Field(default_factory=dict)

    # reliability scores for the run, so the GUI and the notebook need not reopen the PDF
    reliability: dict = Field(default_factory=dict)

    # quality snapshots keyed by measurement point (raw, detected, final)
    quality_snapshots: dict[str, dict] = Field(default_factory=dict)

    # pipeline control
    errors: list[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
