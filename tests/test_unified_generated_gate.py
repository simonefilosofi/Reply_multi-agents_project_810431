"""Pins what the Unified agent does with the code a model returns before that code can reach the approval gate: proposals it cannot execute are discarded, and every generated cleaning function is cleared against its own column's conforming and violating values. The gate runs without an LLM, so these checks stay cheap and deterministic."""
from __future__ import annotations

from noipa_dq.agents.unified import (
    _cleaner_feedback_for,
    _drop_unusable_proposals,
    _examples_by_column,
    _validate_generated_operations,
)
from noipa_dq.models import FixProposal, Operation

_GROUP = ["rata", "aggregation-time"]

_GOOD = """
def clean_value(value):
    import re
    text = str(value).strip()
    if re.fullmatch(r"\\d{6}", text):
        return text
    match = re.fullmatch(r"([A-Za-z]{3})-(\\d{4})", text)
    if match is None:
        return None
    return match.group(2) + {"mar": "03", "lug": "07"}.get(match.group(1).lower(), "01")
"""

_EXAMPLES = {"rata": {
    "dominant": ["202401", "202405"],
    "inconsistent": ["MAR-2024", "LUG-2024"],
    "dtype": "string",
}}


def _proposal(operations: list[Operation], identifier: str = "f1") -> FixProposal:
    return FixProposal(
        id=identifier, description="d", rationale="r", operations=operations,
    )


def _generated(source: str, column: str = "rata") -> Operation:
    return Operation(kind="apply_generated_function", column=column, source=source)


def test_a_proposal_with_no_operations_is_discarded() -> None:
    assert _drop_unusable_proposals([_proposal([])], _GROUP) == []


def test_a_proposal_naming_a_column_outside_the_group_is_discarded() -> None:
    stray = _proposal([Operation(kind="strip_whitespace", column="descrizione'}],")])

    assert _drop_unusable_proposals([stray], _GROUP) == []


def test_a_usable_proposal_survives() -> None:
    usable = _proposal([Operation(kind="strip_whitespace", column="rata")])

    assert _drop_unusable_proposals([usable], _GROUP) == [usable]


def test_a_correct_generated_function_clears_the_gate() -> None:
    assert _validate_generated_operations(_proposal([_generated(_GOOD)]), _EXAMPLES) == []


def test_a_function_that_rewrites_a_conforming_value_is_held_back() -> None:
    source = "def clean_value(value):\n    return str(value) + '!'"

    issues = _validate_generated_operations(_proposal([_generated(source)]), _EXAMPLES)

    assert [issue.category for issue in issues] == ["dominant_value_modified"] * 2


def test_forbidden_source_is_held_back_without_being_executed() -> None:
    source = "def clean_value(value):\n    import os\n    return os.getcwd()"

    issues = _validate_generated_operations(_proposal([_generated(source)]), _EXAMPLES)

    assert [issue.category for issue in issues] == ["forbidden_construct"]


def test_typed_operations_are_not_put_through_the_cleaner_gate() -> None:
    typed = _proposal([Operation(kind="strip_whitespace", column="rata")])

    assert _validate_generated_operations(typed, _EXAMPLES) == []


def test_the_examples_reach_the_gate_in_the_shape_the_context_carries_them() -> None:
    ctx = {"columns": [
        {"name": "rata", "dtype": "string",
         "dominant_example_values": ["202401"], "example_inconsistent_values": ["MAR-2024"]},
        {"name": "spesa", "dtype": "Float64"},
    ]}

    assert _examples_by_column(ctx) == {
        "rata": {"dominant": ["202401"], "inconsistent": ["MAR-2024"], "dtype": "string"},
        "spesa": {"dominant": [], "inconsistent": [], "dtype": "Float64"},
    }


def test_the_feedback_names_the_input_and_the_wrong_output() -> None:
    source = "def clean_value(value):\n    return str(value) + '!'"
    proposal = _proposal([_generated(source)])
    issues = _validate_generated_operations(proposal, _EXAMPLES)

    feedback = _cleaner_feedback_for(proposal, issues)

    assert "'202401'" in feedback
    assert "'202401!'" in feedback
    assert "unchanged" in feedback
