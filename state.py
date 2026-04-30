from __future__ import annotations

from typing import Annotated, Any

import pandas as pd
from pydantic import BaseModel, Field

from models import BaselineFile, ColumnClassification, ColumnPayload, DuplicateResolution, ValidationReport


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

    # classification
    classifications: list[ColumnClassification] = Field(default_factory=list)

    # format validation
    validation_reports: list[ValidationReport] = Field(default_factory=list)

    # pipeline control
    errors: list[str] = Field(default_factory=list)

    class Config:
        arbitrary_types_allowed = True
