"""Pydantic schema defining the DatasetFingerprint model used by the
ProfilerAgent to classify columns by semantic type."""

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


class DatasetFingerprint(BaseModel):
    domain: str
    language: Literal["italian", "english", "mixed"]
    id_columns: List[str]
    numerical_columns: List[str]
    categorical_columns: List[str]
    date_columns: List[str]
    sparse_columns: List[str]
    likely_duplicate_pairs: List[List[str]]
    suggested_key_columns: List[str]
    column_descriptions: Dict[str, str]
    column_constraints: List[Dict[str, Any]] = Field(default_factory=list)
