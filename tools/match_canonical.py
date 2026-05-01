"""Programmatic match cascade resolving an input column name to a canonical baseline id (a shared definition or a dataset-specific canonical column) via exact, accent-and-case-normalized, and fuzzy stages. Also exposes a compact format-summary helper. Consumed by the Semantic agent."""
from __future__ import annotations

import difflib
import unicodedata

from models import ColumnSchema, EnumFormat, RangeFormat, RegexFormat


_FUZZY_CUTOFF = 0.85


def programmatic_match(
    input_name: str,
    domain_catalog: dict[str, ColumnSchema],
    alias_idx: dict[str, str],
) -> str | None:
    if input_name in domain_catalog:
        return _resolve_id(domain_catalog[input_name], input_name)
    if input_name in alias_idx:
        return alias_idx[input_name]

    norm = _normalize(input_name)
    norm_catalog = {_normalize(k): (k, v) for k, v in domain_catalog.items()}
    norm_alias = {_normalize(k): v for k, v in alias_idx.items()}

    if norm in norm_catalog:
        col_name, schema = norm_catalog[norm]
        return _resolve_id(schema, col_name)
    if norm in norm_alias:
        return norm_alias[norm]

    targets = list(norm_catalog.keys()) + [k for k in norm_alias.keys() if k not in norm_catalog]
    close = difflib.get_close_matches(norm, targets, n=1, cutoff=_FUZZY_CUTOFF)
    if close:
        m = close[0]
        if m in norm_catalog:
            col_name, schema = norm_catalog[m]
            return _resolve_id(schema, col_name)
        if m in norm_alias:
            return norm_alias[m]
    return None


def compact_format_summary(spec) -> str | None:
    if isinstance(spec, EnumFormat):
        if len(spec.values) <= 6:
            return f"enum: {spec.values}"
        return f"enum ({len(spec.values)} values)"
    if isinstance(spec, RegexFormat):
        return f"regex: {spec.pattern}"
    if isinstance(spec, RangeFormat):
        return f"range [{spec.min}, {spec.max}]"
    return None


def _resolve_id(schema: ColumnSchema, fallback: str) -> str:
    return schema.canonical_id or fallback


def _normalize(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    out: list[str] = []
    prev_underscore = False
    for ch in stripped.lower():
        if ch.isalnum():
            out.append(ch)
            prev_underscore = False
        elif not prev_underscore:
            out.append("_")
            prev_underscore = True
    return "".join(out).strip("_")
