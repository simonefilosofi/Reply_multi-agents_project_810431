"""Pins that a detected issue nobody can fix is carried forward and stated rather than dropped.
The Unified prompt already requires the model to list every violation it cannot address and to say
why, and _coverage_errors already refuses a response that omits one - but propose_for_group read
only the proposals, so the answer was validated and then discarded. Columns like area_geografica,
a fifth empty with nothing to impute from, reached the report as an unexplained gap. The model's
declaration is now kept, and a deterministic backstop covers what it fails to declare, because
_invoke_with_retry returns the second attempt even when coverage errors remain."""
from __future__ import annotations

import pandas as pd

import noipa_dq.agents.unified as unified
from noipa_dq.models import FixGroupResponse, FormatViolation, ValidationReport
from noipa_dq.state import PipelineState
from noipa_dq.utils.llm import EmptyModelResponse


def _state() -> PipelineState:
    frame = pd.DataFrame({
        "area_geografica": ["Nord", None, None, "Sud"] * 25,
        "importo": [1.0, 2.0, 3.0, 4.0] * 25,
    })
    return PipelineState(
        dataset=frame,
        payload=[unified.ColumnPayload(column_name=c, description="", dtype="")
                 for c in frame.columns],
        validation_reports=[ValidationReport(
            column_name="area_geografica",
            violations=[FormatViolation(
                column_name="area_geografica", row_index=-1, value=50,
                expected_pattern="missing value", kind="completeness", affected_rows=50,
            )],
        )],
    )


def _stub(monkeypatch, outcome) -> None:
    monkeypatch.setattr(unified, "propose_for_group", outcome)


def test_the_models_declaration_is_kept(monkeypatch):
    declared = unified.GroupOutcome(
        proposals=[],
        unaddressed=[unified.UnaddressedViolations(
            group_id="g1", columns=["area_geografica"], violation_ids=["v1"],
            reason="no column determines the geographic area, so a gap cannot be filled",
            source="model",
        )],
    )
    _stub(monkeypatch, lambda *a, **k: declared)

    result = unified.unified_node(_state())

    assert [u.columns for u in result.unaddressed_violations] == [["area_geografica"]]
    assert result.unaddressed_violations[0].source == "model"


def test_a_violation_the_model_forgets_is_still_carried(monkeypatch):
    _stub(monkeypatch, lambda *a, **k: unified.GroupOutcome(proposals=[], unaddressed=[]))

    result = unified.unified_node(_state())

    carried = result.unaddressed_violations
    assert carried, "a violation with neither a proposal nor a declaration must not vanish"
    assert carried[0].source == "pipeline"
    assert "area_geografica" in carried[0].columns


def test_a_group_the_model_could_not_answer_is_carried(monkeypatch):
    def explode(*args, **kwargs):
        raise EmptyModelResponse("no answer")

    _stub(monkeypatch, explode)

    result = unified.unified_node(_state())

    assert [u.source for u in result.unaddressed_violations] == ["pipeline"]
    assert result.errors


def test_the_reason_names_why_the_gap_cannot_be_filled(monkeypatch):
    _stub(monkeypatch, lambda *a, **k: unified.GroupOutcome(proposals=[], unaddressed=[]))

    result = unified.unified_node(_state())

    assert "determines" in result.unaddressed_violations[0].reason


def test_a_group_response_carries_its_declaration_through():
    response = FixGroupResponse(
        proposals=[], unaddressed_violation_ids=["a", "b"],
        rationale_for_unaddressed="monetary values need a rule from the user",
    )

    carried = unified.declared_unaddressed("g3", ["importo"], response)

    assert carried is not None
    assert carried.violation_ids == ["a", "b"]
    assert carried.reason == "monetary values need a rule from the user"
    assert carried.source == "model"


def test_nothing_is_carried_when_the_model_addressed_everything():
    response = FixGroupResponse(proposals=[], unaddressed_violation_ids=[])

    assert unified.declared_unaddressed("g1", ["importo"], response) is None


def test_a_column_a_schema_proposal_covers_is_not_carried():
    from noipa_dq.models import FixProposal, Operation

    carried = [unified.UnaddressedViolations(
        group_id="g1", columns=["_id", "area_geografica"], violation_ids=["v1"],
        reason="r", source="model",
    )]
    rename = FixProposal(
        id="schema_rename__id", description="d", rationale="r", affected_columns=["_id"],
        operations=[Operation(kind="rename_column", column="_id", new_name="id")],
    )

    kept = unified.without_columns_already_actioned(carried, [rename])

    assert [u.columns for u in kept] == [["area_geografica"]]


def test_an_entry_whose_columns_are_all_actioned_is_dropped():
    from noipa_dq.models import FixProposal, Operation

    carried = [unified.UnaddressedViolations(
        group_id="g1", columns=["_id"], violation_ids=["v1"], reason="r", source="model",
    )]
    rename = FixProposal(
        id="schema_rename__id", description="d", rationale="r", affected_columns=["_id"],
        operations=[Operation(kind="rename_column", column="_id", new_name="id")],
    )

    assert unified.without_columns_already_actioned(carried, [rename]) == []
