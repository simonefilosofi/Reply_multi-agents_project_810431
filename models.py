"""Pydantic models for the resolved baseline, the per-column semantic payload, validation reports, and intermediate agent outputs shared across the LangGraph pipeline."""
from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class Casing(str, Enum):
    lowercase = "lowercase"
    uppercase = "uppercase"
    as_is = "as-is"


class EnumFormat(BaseModel):
    type: Literal["enum"] = "enum"
    values: list[Any]


class RegexFormat(BaseModel):
    type: Literal["regex"] = "regex"
    pattern: str


class RangeFormat(BaseModel):
    type: Literal["range"] = "range"
    min: float | None = None
    max: float | None = None


class DateFormat(BaseModel):
    type: Literal["date"] = "date"
    strftime_pattern: str


FormatSpec = Annotated[
    Union[EnumFormat, RegexFormat, RangeFormat, DateFormat],
    Field(discriminator="type"),
]


class ColumnPayload(BaseModel):
    column_name: str
    description: str
    dtype: str
    sample: list[Any] = Field(default_factory=list)
    placeholders: list[Any] = Field(default_factory=list)
    related_columns: list[str] = Field(default_factory=list)
    target_casing: Casing = Casing.as_is
    canonical_hint: str = "NaN"
    canonical_candidates: list[dict] = Field(default_factory=list)


class ColumnSchema(BaseModel):
    column_name: str
    dtype: str
    format: FormatSpec | None = None
    case_convention: str | None = None
    is_nullable: bool = True
    canonical_id: str | None = None


class DatasetSchema(BaseModel):
    description: str = ""
    periodicity: str | None = None
    columns: dict[str, ColumnSchema] = Field(default_factory=dict)


class DomainBaseline(BaseModel):
    description: str = ""
    datasets: dict[str, DatasetSchema] = Field(default_factory=dict)


class GlobalConventions(BaseModel):
    naming_convention: str | None = None
    naming_regex: str | None = None
    encoding: str | None = None
    csv_separator: str | None = None
    decimal_separator: str | None = None
    filename_convention_monthly: str | None = None
    filename_convention_annual: str | None = None
    k_anonymity_floor_for_person_counts: int | None = None


class BaselineFile(BaseModel):
    domains: dict[str, DomainBaseline] = Field(default_factory=dict)
    shared_definitions: dict[str, ColumnSchema] = Field(default_factory=dict)
    global_conventions: GlobalConventions = Field(default_factory=GlobalConventions)
    observations: dict[str, list[str]] = Field(default_factory=dict)


class DuplicateResolution(BaseModel):
    group: list[str]
    data_survivor: str
    canonical_name: str
    rationale: str
    dropped: list[str]
    cells_backfilled: int = 0
    cells_overwritten: dict[str, int] = Field(default_factory=dict)
    values_lost: dict[str, list] = Field(default_factory=dict)


ViolationKind = Literal["format", "completeness", "schema", "consistency", "uniqueness"]


class FormatViolation(BaseModel):
    column_name: str
    row_index: int
    value: Any
    expected_pattern: str | None
    kind: ViolationKind
    affected_rows: int = 1


class ValidationReport(BaseModel):
    column_name: str
    violations: list[FormatViolation] = Field(default_factory=list)
    detected_total: int | None = None


OperationKind = Literal[
    "replace_values",
    "normalize_numeric",
    "normalize_date",
    "normalize_period",
    "strip_whitespace",
    "collapse_casing",
    "round_decimals",
    "cast_dtype",
    "impute_from_lookup",
    "drop_column",
    "rename_column",
    "drop_duplicate_rows",
    "apply_generated_function",
]


class ValueMapping(BaseModel):
    value: str
    replacement: str | None = None


class Operation(BaseModel):
    kind: OperationKind
    column: str = ""
    mapping: list[ValueMapping] = Field(default_factory=list)
    digits: int = 2
    dtype: str = ""
    new_name: str = ""
    subset: list[str] = Field(default_factory=list)
    source: str = ""


CleanerIssueCategory = Literal[
    "malformed_source",
    "forbidden_construct",
    "runtime_exception",
    "dominant_value_modified",
    "outlier_unchanged",
    "not_parseable_as_target_dtype",
]


class CleanerIssue(BaseModel):
    category: CleanerIssueCategory
    message: str
    input_value: str | None = None
    actual_output: str | None = None
    expected_behavior: str = ""


class CleanerRepair(BaseModel):
    input_value: str
    actual_output: str | None = None
    expected_output: str | None = None
    fix_note: str


class CleanerDiagnosis(BaseModel):
    root_cause: str
    bug_location: str
    planned_fix: str
    exact_repairs: list[CleanerRepair] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"


class FixProposal(BaseModel):
    id: str
    description: str
    rationale: str
    addresses_violations: list[str] = Field(default_factory=list)
    affected_columns: list[str] = Field(default_factory=list)
    estimated_rows_affected: int = 0
    operations: list[Operation] = Field(default_factory=list)
    code: str = ""
    depends_on: list[str] = Field(default_factory=list)


class FixGroupResponse(BaseModel):
    proposals: list[FixProposal] = Field(default_factory=list)
    unaddressed_violation_ids: list[str] = Field(default_factory=list)
    rationale_for_unaddressed: str = ""


class FixReviewResponse(BaseModel):
    decision: Literal["approve", "revise"]
    feedback: str = ""


class ImputationHint(BaseModel):
    target_column: str
    strategy: Literal["lookup"] = "lookup"
    predictor_columns: list[str]
    mapping: dict[str, Any]
    path: Literal["raw", "normalized"]
    purity: float
    coverage: float
    confidence: Literal["strict", "dominant"]
    temporally_stable: bool = True
    rationale: str = ""


class AnomalyEntry(BaseModel):
    row_index: int
    value: Any
    reason: str


class AnomalyReport(BaseModel):
    column_name: str
    method: str  # "iqr" or "rare_category"
    anomalies: list[AnomalyEntry] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)
    comment: str = ""
