"""Pins that an approved fix which does not land says so. A skip used to be filtered out of the failures list, so a proposal the reviewer had accepted could vanish between the gate and the dataset leaving state.errors empty; on attivazioniCessazioni that hid a format repair whose absence left 1902 violations standing."""
from __future__ import annotations

import pandas as pd

from noipa_dq.agents.apply_fixes import _failure_detail, apply_fixes_node
from noipa_dq.models import ColumnPayload, FixProposal, Operation
from noipa_dq.state import PipelineState


def _proposal(identifier: str, depends_on: list[str] | None = None) -> FixProposal:
    return FixProposal(
        id=identifier, description="d", rationale="r", affected_columns=["rata"],
        depends_on=depends_on or [],
        operations=[Operation(kind="strip_whitespace", column="rata")],
    )


def _state(proposals: list[FixProposal]) -> PipelineState:
    return PipelineState(
        dataset=pd.DataFrame({"rata": [" 202401 ", "202403"]}),
        payload=[ColumnPayload(column_name="rata", description="period", dtype="string")],
        proposed_fixes=proposals,
        approved_fix_ids=[p.id for p in proposals],
    )


def test_a_fix_skipped_for_a_missing_dependency_reaches_the_errors() -> None:
    result = apply_fixes_node(_state([_proposal("f1", depends_on=["never_accepted"])]))

    assert result.applied_fix_ids == []
    assert len(result.errors) == 1
    assert "f1" in result.errors[0] and "missing deps" in result.errors[0]


def test_a_fix_skipped_as_a_duplicate_reaches_the_errors() -> None:
    result = apply_fixes_node(_state([_proposal("f1"), _proposal("f2")]))

    assert result.applied_fix_ids == ["f1"]
    assert any("f2" in error and "duplicate" in error for error in result.errors)


def test_a_fix_that_lands_leaves_no_error_behind() -> None:
    result = apply_fixes_node(_state([_proposal("f1")]))

    assert result.applied_fix_ids == ["f1"]
    assert result.errors == []


def test_the_detail_prefers_the_most_specific_reason_available() -> None:
    assert _failure_detail({"status": "error", "error": "boom"}) == "boom"
    assert "budget" in _failure_detail(
        {"status": "rejected", "invariant_violations": ["over budget"]}
    )
    assert _failure_detail({"status": "skipped", "reason": "missing deps: ['x']"}).startswith(
        "missing deps"
    )
    assert _failure_detail({"status": "skipped"}) == "skipped"
