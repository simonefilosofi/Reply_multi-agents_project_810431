"""Pins that a group whose proposals the model cannot produce costs that group and no more. A run
over trasferimentiPersonale ended in the Unified agent because one reply reached the output limit:
the exception travelled out of the node and the whole pipeline stopped, so no report was written
for a dataset the earlier stages had already measured and repaired. A group that yields nothing
should be recorded on state.errors and skipped, leaving the remaining groups, the schema proposals
and the report intact."""
from __future__ import annotations

import pandas as pd
import pytest

import agents.unified as unified
from models import ColumnPayload, FormatViolation, ValidationReport
from state import PipelineState
from utils.llm import EmptyModelResponse


def _state() -> PipelineState:
    frame = pd.DataFrame({"importo": ["1,5", "2,5", "3,5"], "note": [None, None, None]})
    return PipelineState(
        dataset=frame,
        payload=[ColumnPayload(column_name=c, description="", dtype="") for c in frame.columns],
        validation_reports=[
            ValidationReport(
                column_name="importo",
                violations=[FormatViolation(
                    column_name="importo", row_index=0, value="1,5",
                    expected_pattern="decimal point", kind="format",
                )],
            ),
            ValidationReport(
                column_name="note",
                violations=[FormatViolation(
                    column_name="note", row_index=-1, value=3,
                    expected_pattern="sparse column: 100.0% null", kind="schema",
                    affected_rows=3,
                )],
            ),
        ],
    )


def test_a_group_the_model_cannot_answer_is_skipped_not_fatal(monkeypatch):
    def explode(*args, **kwargs):
        raise EmptyModelResponse("no answer")

    monkeypatch.setattr(unified, "propose_for_group", explode)

    result = unified.unified_node(_state())

    assert isinstance(result, PipelineState)
    assert any("importo" in error or "g1" in error for error in result.errors)


def test_the_run_still_produces_the_schema_proposals(monkeypatch):
    def explode(*args, **kwargs):
        raise EmptyModelResponse("no answer")

    monkeypatch.setattr(unified, "propose_for_group", explode)

    result = unified.unified_node(_state())

    assert [p.id for p in result.proposed_fixes if "note" in p.affected_columns]


def test_an_unexpected_error_still_stops_the_run(monkeypatch):
    def explode(*args, **kwargs):
        raise KeyError("a genuine bug")

    monkeypatch.setattr(unified, "propose_for_group", explode)

    with pytest.raises(KeyError):
        unified.unified_node(_state())


def test_a_truncated_reply_inside_the_chain_degrades_to_no_proposals(monkeypatch):
    class Chain:
        def invoke(self, messages):
            raise EmptyModelResponse("no answer")

    assert unified._invoke_with_retry(Chain(), "system", {}, set(), ["importo"]) is None
