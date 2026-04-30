"""Pydantic schema defining the DatasetFingerprint model used by the
ProfilerAgent to classify columns by semantic type.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class DatasetFingerprint(BaseModel):
    domain: str
    language: Literal["italian", "english", "mixed"]
    id_columns: list[str]
    numerical_columns: list[str]
    categorical_columns: list[str]
    date_columns: list[str]
    sparse_columns: list[str]
    likely_duplicate_pairs: list[list[str]]
    suggested_key_columns: list[str]
    column_descriptions: dict[str, str]
    column_constraints: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_llm_quirks(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cd = data.get("column_descriptions")
        if isinstance(cd, list):
            merged: dict[str, str] = {}
            for item in cd:
                if isinstance(item, dict):
                    for k, v in item.items():
                        merged[str(k)] = str(v)
            data["column_descriptions"] = merged
        if data.get("language"):
            data["language"] = str(data["language"]).lower()
        return data
