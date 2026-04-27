"""Tests for state_demo.issues: round-trip every Issue subclass and prove extra=forbid."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from state_demo.issues import (
    ISSUE_ADAPTER,
    ISSUE_SUBCLASSES,
    IssueBase,
    parse_issue,
)


def _minimal_kwargs(cls: type[IssueBase]) -> dict[str, Any]:
    """Return the minimum set of kwargs required to instantiate ``cls`` cleanly."""
    base: dict[str, Any] = {
        "column": "col_x",
        "detail": "test detail",
        "severity": "high",
        "type": cls.model_fields["type"].default,
    }
    name = cls.__name__
    if name == "MissingValuesIssue":
        base.update(missing_count=1, total=10)
    elif name == "DuplicateColumnsIssue":
        base.pop("column")
        base.update(column_a="col_x", column_b="col_y")
    elif name == "DuplicateKeyIssue":
        base.pop("column")
        base.update(key_columns=("col_x",))
    elif name == "DateOrderIssue":
        base.pop("column")
        base.update(column_a="start", column_b="end", violations=3)
    elif name == "LookupImputabilityIssue":
        base.update(mapping_source="col_y", coverage=0.95, n_imputable=10)
    elif name == "FormatPatternViolationIssue":
        base.update(pattern=r"^\d{16}$", description="codice fiscale")
    return base


@pytest.mark.parametrize(
    "cls", ISSUE_SUBCLASSES, ids=[c.model_fields["type"].default for c in ISSUE_SUBCLASSES]
)
def test_subclass_round_trips_through_adapter(cls: type[IssueBase]) -> None:
    """Every subclass round-trips: instantiate -> dump -> parse -> same type/column."""
    obj = cls(**_minimal_kwargs(cls))
    dumped = obj.model_dump()
    parsed = parse_issue(dumped)
    assert parsed.model_dump()["type"] == obj.model_dump()["type"]
    assert parsed.column == obj.column


@pytest.mark.parametrize(
    "cls", ISSUE_SUBCLASSES, ids=[c.model_fields["type"].default for c in ISSUE_SUBCLASSES]
)
def test_subclass_rejects_unknown_field(cls: type[IssueBase]) -> None:
    """extra='forbid' must reject any unknown keyword on every subclass."""
    kw = _minimal_kwargs(cls)
    kw["spurious_field"] = "boom"
    with pytest.raises(ValidationError):
        cls(**kw)


def test_format_pattern_violation_requires_pattern() -> None:
    """B1 closure: FormatPatternViolationIssue cannot be built without a pattern."""
    with pytest.raises(ValidationError) as exc_info:
        ISSUE_ADAPTER.validate_python(
            {
                "type": "format_pattern_violation",
                "column": "codice",
                "detail": "bad codes",
                "severity": "high",
                "description": "codice fiscale",
            }
        )
    assert any(err["loc"][-1] == "pattern" for err in exc_info.value.errors())


def test_duplicate_columns_auto_populates_column() -> None:
    """DuplicateColumnsIssue.column is auto-filled from column_a when omitted."""
    issue = parse_issue(
        {
            "type": "duplicate_columns",
            "column_a": "nome",
            "column_b": "name",
            "detail": "near-duplicate",
            "severity": "medium",
        }
    )
    assert issue.column == "nome"


def test_date_order_auto_populates_column() -> None:
    """DateOrderIssue.column is auto-filled from column_a when omitted."""
    issue = parse_issue(
        {
            "type": "date_order",
            "column_a": "start_date",
            "column_b": "end_date",
            "violations": 4,
            "detail": "end before start",
            "severity": "high",
        }
    )
    assert issue.column == "start_date"


def test_duplicate_key_auto_populates_column() -> None:
    """DuplicateKeyIssue.column is auto-filled from key_columns[0] when omitted."""
    issue = parse_issue(
        {
            "type": "duplicate_key",
            "key_columns": ["codice", "anno"],
            "detail": "dup keys",
            "severity": "high",
        }
    )
    assert issue.column == "codice"


def test_subclasses_match_constants_one_to_one() -> None:
    """Every subclass type must have a matching key in constants.ISSUE_TYPES and vice versa."""
    from state_demo.constants import ISSUE_TYPES

    sub_types = {c.model_fields["type"].default for c in ISSUE_SUBCLASSES}
    const_types = set(ISSUE_TYPES)
    assert sub_types == const_types, (
        f"Drift between Issue subclasses and constants.ISSUE_TYPES: "
        f"only-in-subclasses={sorted(sub_types - const_types)} "
        f"only-in-constants={sorted(const_types - sub_types)}"
    )
