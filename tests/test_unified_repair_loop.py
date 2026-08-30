"""Pins the escalation the repair loop performs when a generated cleaning function keeps failing. A failure that is new gets deterministic feedback built from the findings; a failure identical to the previous one gets the critic instead, once, because repeating feedback the generator already ignored only spends attempts. The loop is driven here with stubbed validation and review so the escalation is observable without an LLM."""
from __future__ import annotations

import pandas as pd
import pytest

import agents.unified as unified
from models import CleanerIssue, FixProposal, FixReviewResponse, Operation

_EXAMPLES = {"rata": {"dominant": ["202401"], "inconsistent": ["MAR-2024"], "dtype": "string"}}


def _issue(input_value: str) -> CleanerIssue:
    return CleanerIssue(
        category="dominant_value_modified",
        message="rewrote a conforming value.",
        input_value=input_value,
        actual_output=input_value + "!",
        expected_behavior="return it unchanged.",
    )


def _proposal(identifier: str = "f1") -> FixProposal:
    return FixProposal(
        id=identifier, description="d", rationale="r", affected_columns=["rata"],
        operations=[Operation(kind="apply_generated_function", column="rata", source="src")],
    )


class _ApprovingReviewChain:
    def invoke(self, _messages):
        return FixReviewResponse(decision="approve")


@pytest.fixture
def loop(monkeypatch):
    """Runs the real loop over stubbed collaborators and records how it asked for repairs."""
    calls: dict[str, list] = {"deterministic": [], "critic": []}

    monkeypatch.setattr(unified, "structured_model", lambda *_a, **_k: _ApprovingReviewChain())
    monkeypatch.setattr(unified, "load_prompt", lambda _name: "")
    monkeypatch.setattr(unified, "trial_execute", lambda *a, **k: {
        "status": "applied", "invariant_violations": [], "rows_changed": 1,
        "violation_delta": {}, "diff_sample": [],
    })
    monkeypatch.setattr(unified, "_breaks_invariants", lambda *a, **k: False)
    monkeypatch.setattr(
        unified, "_cleaner_feedback_for",
        lambda proposal, issues: calls["deterministic"].append(issues) or "deterministic",
    )
    monkeypatch.setattr(
        unified, "_critic_feedback_for",
        lambda proposal, issues, examples: calls["critic"].append(issues) or "critic",
    )

    def run(issue_sequence: list[list[CleanerIssue]]) -> tuple[list[FixProposal], dict, list[str]]:
        remaining = list(issue_sequence)
        asked: list[str] = []
        monkeypatch.setattr(
            unified, "_validate_generated_operations",
            lambda *_a: remaining.pop(0) if remaining else [],
        )

        def regenerate(feedback: str) -> FixProposal:
            asked.append(feedback)
            return _proposal("regenerated")

        finalized = unified._review_and_revise_proposals(
            proposals=[_proposal()], group=["rata"], examples_by_column=_EXAMPLES,
            df=pd.DataFrame({"rata": ["202401"]}), removable_by_column={}, value_corrections={},
            specs_by_col={}, reports_by_name={}, imputation_hints={}, regenerate=regenerate,
        )
        return finalized, calls, asked

    return run


def test_a_function_that_passes_first_time_is_never_regenerated(loop) -> None:
    finalized, calls, asked = loop([[]])

    assert [p.id for p in finalized] == ["f1"]
    assert asked == []
    assert calls["critic"] == []


def test_a_new_failure_gets_deterministic_feedback(loop) -> None:
    _finalized, calls, asked = loop([[_issue("202401")], []])

    assert asked == ["deterministic"]
    assert len(calls["deterministic"]) == 1
    assert calls["critic"] == []


def test_the_same_failure_twice_escalates_to_the_critic(loop) -> None:
    _finalized, calls, asked = loop([[_issue("202401")], [_issue("202401")], []])

    assert asked == ["deterministic", "critic"]
    assert len(calls["critic"]) == 1


def test_a_different_second_failure_does_not_escalate(loop) -> None:
    _finalized, calls, asked = loop([[_issue("202401")], [_issue("202405")], []])

    assert asked == ["deterministic", "deterministic"]
    assert calls["critic"] == []


def test_the_critic_is_spent_only_once(loop) -> None:
    repeated = [_issue("202401")]
    _finalized, calls, asked = loop([repeated, repeated, repeated])

    assert asked.count("critic") == 1


def test_a_proposal_still_failing_at_the_end_never_reaches_the_gate(loop) -> None:
    finalized, _calls, _asked = loop([[_issue("202401")]] * 6)

    assert finalized == []
