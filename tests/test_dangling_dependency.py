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


def test_a_dependency_dropped_during_review_strands_its_dependent():
    from agents.unified import _without_dangling_dependencies

    survived = [_proposal("f1", depends=["f2"])]

    assert _without_dangling_dependencies(survived) == []


def test_review_survivors_that_still_have_their_dependency_are_kept():
    from agents.unified import _without_dangling_dependencies

    survived = [_proposal("f1", depends=["f2"]), _proposal("f2")]

    assert [p.id for p in _without_dangling_dependencies(survived)] == ["f1", "f2"]


def test_a_dependency_collapsed_into_a_schema_fix_strands_its_dependent():
    from agents.unified import _without_dangling_dependencies

    schema = FixProposal(
        id="schema_drop_note", description="d", rationale="r", affected_columns=["note"],
        operations=[Operation(kind="drop_column", column="note")])
    survived = [_proposal("g2_f1", depends=["g2_f2"])]

    assert _without_dangling_dependencies([schema] + survived) == [schema]


def test_a_proposal_depending_on_itself_is_dropped():
    from agents.unified import _without_dangling_dependencies

    assert _without_dangling_dependencies([_proposal("f2", depends=["f2"])]) == []


def test_a_self_dependency_also_strands_whatever_relied_on_it():
    from agents.unified import _without_dangling_dependencies

    proposals = [_proposal("f1", depends=["f2"]), _proposal("f2", depends=["f2"])]

    assert _without_dangling_dependencies(proposals) == []


def test_two_proposals_depending_on_each_other_are_both_dropped():
    from agents.unified import _without_dangling_dependencies

    proposals = [_proposal("f1", depends=["f2"]), _proposal("f2", depends=["f1"])]

    assert _without_dangling_dependencies(proposals) == []


def test_a_chain_of_dependencies_is_kept_in_full():
    from agents.unified import _without_dangling_dependencies

    proposals = [_proposal("f1", depends=["f2"]), _proposal("f2", depends=["f3"]),
                 _proposal("f3")]

    assert [p.id for p in _without_dangling_dependencies(proposals)] == ["f1", "f2", "f3"]
