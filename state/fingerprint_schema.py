from pydantic import BaseModel
from typing import Dict, List, Literal


class DatasetFingerprint(BaseModel):
    domain: Literal["financial", "demographic", "geographic",
                    "health", "logistics", "government", "generic"]
    language: Literal["italian", "english", "mixed"]
    id_columns: List[str]
    numerical_columns: List[str]
    categorical_columns: List[str]
    date_columns: List[str]
    sparse_columns: List[str]
    likely_duplicate_pairs: List[List[str]]
    suggested_key_columns: List[str]
    column_descriptions: Dict[str, str]
