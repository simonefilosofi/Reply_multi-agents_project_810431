from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Casing(str, Enum):
    lowercase = "lowercase"
    uppercase = "uppercase"
    as_is = "as-is"


class ColumnPayload(BaseModel):
    column_name: str
    domain: str
    dtype: str
    sample: list[Any] = Field(default_factory=list)
    placeholders: list[Any] = Field(default_factory=list)
    related_columns: list[str] = Field(default_factory=list)
    target_casing: Casing = Casing.as_is


class ColumnSchema(BaseModel):
    column_name: str
    dtype: str
    format_pattern: str | None = None


class DomainBaseline(BaseModel):
    domain: str
    columns: list[ColumnSchema] = Field(default_factory=list)


class BaselineFile(BaseModel):
    domains: list[DomainBaseline] = Field(default_factory=list)


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
