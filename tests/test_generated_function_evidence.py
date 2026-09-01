"""Pins that a generated cleaning function is never approved without being executed. The gate
judged each function against the example values collected for its column, but a column with no
recorded examples produced an empty value list, over which the cleaner runs zero times and returns
zero issues - so the proposal cleared the gate untested and could still raise on the real column.
A run over attivazioniCessazioni ended with apply_fixes reporting `invalid literal for int() with
base 10: '40.0'` from a function that had been approved. Evidence now falls back to the column
itself, and a function that cannot be run against anything is refused rather than assumed sound."""
from __future__ import annotations

import pandas as pd

from agents.unified import _validate_generated_operations
from models import FixProposal, Operation

_BREAKS_ON_FLOAT_TEXT = """def clean_value(value):
    text = str(value).strip()
    num = int(text)
    if num < 0:
        return str(-num)
    return text
"""

_SOUND = """def clean_value(value):
    text = str(value).strip()
    if text.startswith("-"):
        return text[1:]
    return text
"""


def _proposal(source: str, column: str = "cessazioni") -> FixProposal:
    return FixProposal(
        id="f1", description="d", rationale="r", affected_columns=[column],
        operations=[Operation(kind="apply_generated_function", column=column, source=source)],
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"cessazioni": [40.0, 12.0, 250.0, None, -3.0]})


def test_a_function_is_run_against_the_column_when_no_examples_were_collected():
    issues = _validate_generated_operations(_proposal(_BREAKS_ON_FLOAT_TEXT), {}, _frame())

    assert issues, "a function that raises on the column's own values must not clear the gate"
    assert any(issue.category == "runtime_exception" for issue in issues)


def test_a_sound_function_still_clears_the_gate_without_examples():
    assert _validate_generated_operations(_proposal(_SOUND), {}, _frame()) == []


def test_recorded_examples_are_preferred_over_sampling():
    examples = {"cessazioni": {"dominant": ["40"], "inconsistent": ["-3"], "dtype": "int64"}}

    assert _validate_generated_operations(
        _proposal(_BREAKS_ON_FLOAT_TEXT), examples, _frame()
    ) == []


def test_a_function_with_nothing_to_run_against_is_refused():
    empty = pd.DataFrame({"cessazioni": [None, None]})

    issues = _validate_generated_operations(_proposal(_BREAKS_ON_FLOAT_TEXT), {}, empty)

    assert [issue.category for issue in issues] == ["not_validated"]


def test_a_column_absent_from_the_frame_is_refused():
    issues = _validate_generated_operations(
        _proposal(_BREAKS_ON_FLOAT_TEXT, column="missing"), {}, _frame()
    )

    assert [issue.category for issue in issues] == ["not_validated"]


def test_operations_that_are_not_generated_functions_are_ignored():
    proposal = FixProposal(
        id="f1", description="d", rationale="r", affected_columns=["cessazioni"],
        operations=[Operation(kind="drop_column", column="cessazioni")],
    )

    assert _validate_generated_operations(proposal, {}, _frame()) == []
