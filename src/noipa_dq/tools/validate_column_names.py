"""Validates column names against the baseline naming convention and derives a conforming name for those that violate it. Backs the Schema Validation naming check and the deterministic canonical-name election of the Duplicate Column agent."""
from __future__ import annotations

import re

from noipa_dq.models import GlobalConventions

_DEFAULT_NAMING_REGEX = "^[a-z][a-z0-9_]*(_[A-Z]{2,})?$"
_NON_ALPHANUMERIC = re.compile(r"[^0-9a-zA-Z]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_LEADING_DIGIT = re.compile(r"^[0-9]")
_DIGIT_PREFIX = "col_"


def naming_regex(conventions: GlobalConventions | None) -> str:
    if conventions is not None and conventions.naming_regex:
        return conventions.naming_regex
    return _DEFAULT_NAMING_REGEX


def is_conforming(name: str, conventions: GlobalConventions | None) -> bool:
    return re.match(naming_regex(conventions), name) is not None


def normalize_column_name(name: str, conventions: GlobalConventions | None) -> str:
    candidate = _CAMEL_BOUNDARY.sub("_", name.strip())
    candidate = _NON_ALPHANUMERIC.sub("_", candidate).strip("_").lower()
    candidate = re.sub(r"_+", "_", candidate)
    if not candidate:
        return _DIGIT_PREFIX.rstrip("_")
    if _LEADING_DIGIT.match(candidate):
        candidate = f"{_DIGIT_PREFIX}{candidate}"
    if is_conforming(candidate, conventions):
        return candidate
    return re.sub(r"[^a-z0-9_]", "", candidate) or _DIGIT_PREFIX.rstrip("_")


def uniquify(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    index = 2
    while f"{name}_{index}" in taken:
        index += 1
    return f"{name}_{index}"


def validate_column_names(
    columns: list[str], conventions: GlobalConventions | None
) -> list[tuple[str, str]]:
    return [
        (column, normalize_column_name(column, conventions))
        for column in columns
        if not is_conforming(column, conventions)
    ]
