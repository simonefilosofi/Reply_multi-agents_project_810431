"""Embeddings-based retriever resolving an input column to top-k baseline candidates from column_descriptions.json. Embeds the baseline catalog once and caches it to disk; ranks candidates by description cosine similarity boosted by sample-value overlap and dtype agreement. Consumed by the Semantic agent when programmatic name matching is insufficient."""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
from openai import OpenAI

_MODEL = "text-embedding-3-small"
_DEFAULT_DESCRIPTIONS = Path(__file__).resolve().parents[3] / "data" / "registry" / "column_descriptions.json"
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def _entry_text(name: str, description: str, samples: list) -> str:
    sample_str = ", ".join(str(s) for s in samples[:5])
    return f"{name}: {description} | samples: {sample_str}"


def _normalize_dtype(d: str) -> str:
    d = d.lower()
    if "int" in d:
        return "int"
    if "float" in d or "double" in d or "decimal" in d:
        return "float"
    if "date" in d or "time" in d:
        return "datetime"
    if "bool" in d:
        return "bool"
    return "string"


def _load_index(descriptions_path: Path) -> tuple[list[dict], np.ndarray]:
    cache_path = descriptions_path.with_suffix(".embeddings.pkl")
    entries = json.loads(descriptions_path.read_text(encoding="utf-8"))
    if cache_path.exists():
        with cache_path.open("rb") as f:
            cached = pickle.load(f)
        if cached.get("count") == len(entries) and cached.get("model") == _MODEL:
            return entries, cached["matrix"]
    texts = [_entry_text(e["column_name"], e.get("description", ""), e.get("sample", [])) for e in entries]
    response = _get_client().embeddings.create(model=_MODEL, input=texts)
    matrix = np.array([d.embedding for d in response.data], dtype=np.float32)
    matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
    with cache_path.open("wb") as f:
        pickle.dump({"count": len(entries), "model": _MODEL, "matrix": matrix}, f)
    return entries, matrix


def lookup_descriptor(
    canonical_id: str,
    descriptions_path: Path = _DEFAULT_DESCRIPTIONS,
) -> dict | None:
    if not canonical_id or canonical_id == "NaN":
        return None
    entries, _ = _load_index(descriptions_path)
    for entry in entries:
        if entry["column_name"] == canonical_id:
            return entry
    return None


def retrieve_top_k(
    input_name: str,
    dtype: str,
    samples: list,
    description: str = "",
    k: int = 5,
    descriptions_path: Path = _DEFAULT_DESCRIPTIONS,
) -> list[dict]:
    entries, matrix = _load_index(descriptions_path)
    text = _entry_text(input_name, description, samples)
    response = _get_client().embeddings.create(model=_MODEL, input=[text])
    q = np.array(response.data[0].embedding, dtype=np.float32)
    q /= np.linalg.norm(q)
    cos = matrix @ q
    sample_set = {str(s).lower().strip() for s in samples if s is not None}
    dtype_norm = _normalize_dtype(dtype)
    scores = np.empty(len(entries), dtype=np.float32)
    for i, entry in enumerate(entries):
        overlap = 0.0
        if sample_set:
            entry_set = {str(s).lower().strip() for s in entry.get("sample", [])}
            if entry_set:
                overlap = len(sample_set & entry_set) / len(sample_set)
        dtype_bonus = 0.1 if _normalize_dtype(entry.get("dtype", "")) == dtype_norm else 0.0
        scores[i] = float(cos[i]) + 0.3 * overlap + dtype_bonus
    order = np.argsort(scores)[::-1][:k]
    return [
        {
            "canonical_id": entries[i]["column_name"],
            "description": entries[i].get("description", ""),
            "dtype": entries[i].get("dtype", ""),
            "sample": entries[i].get("sample", []),
            "score": round(float(scores[i]), 3),
        }
        for i in order
    ]
