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


class ColumnClassification(BaseModel):
    column_name: str
    normalized_name: str
    description: str


class FormatViolation(BaseModel):
    column_name: str
    row_index: int
    value: Any
    expected_pattern: str | None


class ValidationReport(BaseModel):
    column_name: str
    violations: list[FormatViolation] = Field(default_factory=list)


class FixProposal(BaseModel):
    id: str
    description: str
    rationale: str
    addresses_violations: list[str] = Field(default_factory=list)
    affected_columns: list[str] = Field(default_factory=list)
    estimated_rows_affected: int = 0
    code: str
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
    rationale: str = ""
