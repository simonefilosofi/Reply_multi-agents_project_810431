"""Pins that a proposal depending on one the model did not emit never reaches the gate. Proposals
may depend on each other, and _coverage_errors already refuses a response naming an unknown
dependency - but _invoke_with_retry returns the second attempt even when errors remain, so such a
proposal survived, was shown to the reviewer, was approved, and then failed in apply_fixes with
`missing deps`. A proposal that cannot execute whatever the reviewer decides is not a proposal."""
from __future__ import annotations

from agents.unified import _drop_unusable_proposals
from models import FixProposal, Operation


def _proposal(identifier: str, column: str = "imposta", depends: list[str] | None = None) -> FixProposal:
    return FixProposal(
        id=identifier, description="d", rationale="r", affected_columns=[column],
        operations=[Operation(kind="replace_values", column=column)],
        depends_on=depends or [],
    )


def test_a_proposal_depending_on_a_missing_one_is_dropped():
    kept = _drop_unusable_proposals([_proposal("f1", depends=["f2"])], ["imposta"])

    assert kept == []


def test_a_proposal_whose_dependency_is_present_survives():
    kept = _drop_unusable_proposals(
        [_proposal("f1", depends=["f2"]), _proposal("f2")], ["imposta"]
    )

    assert [p.id for p in kept] == ["f1", "f2"]


def test_a_dependency_on_a_proposal_that_was_itself_dropped_is_dropped_too():
    unusable = FixProposal(id="f2", description="d", rationale="r", operations=[])
    kept = _drop_unusable_proposals([_proposal("f1", depends=["f2"]), unusable], ["imposta"])

    assert kept == []


def test_a_proposal_with_no_dependencies_is_untouched():
    assert [p.id for p in _drop_unusable_proposals([_proposal("f1")], ["imposta"])] == ["f1"]
