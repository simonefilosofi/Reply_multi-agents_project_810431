"""Pins the names the Unified agent's proposals carry to the gate, the report and the change log.
The model chooses an opaque token for each proposal it writes - f1, f2 - which used to reach the
reviewer as g2_f2 while the deterministic proposals beside it read schema_drop_note. _namespace_
proposals replaces the token with a name built from the operation and the column, so both kinds of
proposal are named the same way. Two properties matter beyond legibility: two proposals naming the
same operation on the same column must stay distinct, because approved_fix_ids is keyed by name
and a collision would silently apply one fix twice and lose the other; and depends_on must be
rewritten in the same pass, because it cites the tokens that are being replaced."""
from __future__ import annotations

from agents.unified import _namespace_proposals
from models import FixProposal, Operation


def _proposal(identifier: str, kind: str, column: str = "", depends: list[str] | None = None) -> FixProposal:
    operations = [Operation(kind=kind, column=column)] if kind else []
    return FixProposal(
        id=identifier, description="d", rationale="r",
        operations=operations, depends_on=depends or [],
    )


def test_the_name_states_the_operation_and_the_column():
    named = _namespace_proposals("g2", [
        _proposal("f1", "impute_from_lookup", "descrizione"),
        _proposal("f2", "replace_values", "imposta"),
    ])

    assert [p.id for p in named] == ["impute_from_lookup_descrizione", "replace_values_imposta"]


def test_a_generated_function_is_named_for_the_column_it_cleans():
    named = _namespace_proposals("g2", [_proposal("f1", "apply_generated_function", "rata")])

    assert named[0].id == "clean_rata"


def test_the_same_operation_twice_on_one_column_stays_distinct():
    named = _namespace_proposals("g2", [
        _proposal("f1", "replace_values", "imposta"),
        _proposal("f2", "replace_values", "imposta"),
        _proposal("f3", "replace_values", "imposta"),
    ])

    assert [p.id for p in named] == [
        "replace_values_imposta", "replace_values_imposta_2", "replace_values_imposta_3",
    ]
    assert len({p.id for p in named}) == 3


def test_a_column_name_breaking_the_convention_yields_a_usable_name():
    named = _namespace_proposals("g2", [
        _proposal("f1", "replace_values", "cod imposta ext"),
        _proposal("f2", "rename_column", "ente%code"),
    ])

    assert [p.id for p in named] == ["replace_values_cod_imposta_ext", "rename_column_ente_code"]


def test_depends_on_follows_the_rename():
    named = _namespace_proposals("g2", [
        _proposal("f1", "impute_from_lookup", "descrizione"),
        _proposal("f2", "cast_dtype", "descrizione", depends=["f1"]),
    ])

    assert named[1].depends_on == ["impute_from_lookup_descrizione"]


def test_every_proposal_carries_the_group_it_came_from():
    named = _namespace_proposals("g3", [_proposal("f1", "replace_values", "imposta")])

    assert named[0].group_id == "g3"


def test_an_operation_without_a_column_still_yields_a_name():
    named = _namespace_proposals("g2", [
        _proposal("f1", "drop_duplicate_rows"),
        _proposal("f2", ""),
    ])

    assert [p.id for p in named] == ["drop_duplicate_rows", "g2_fix"]
