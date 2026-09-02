"""Pins the refusal to fill a column too sparse to speak for itself. The rule was stated in the Unified agent's prompt and nowhere else, and a run on attivazioniCessazioni produced a proposal to impute `note`, a column 98.5% empty, straight past it. A rule that can be checked by executing the fix belongs in the check, not in the instructions."""
from __future__ import annotations

import pandas as pd

from noipa_dq.models import FixProposal, Operation
from noipa_dq.tools.fix_invariants import check_invariants

_HINT = {"note": {"mapping": {"a": "x"}}}


def _proposal() -> FixProposal:
    return FixProposal(
        id="f1", description="d", rationale="r", affected_columns=["note"],
        operations=[Operation(kind="impute_from_lookup", column="note")],
    )


def _column(populated: int, empty: int) -> pd.DataFrame:
    return pd.DataFrame({"note": ["value"] * populated + [None] * empty})


def _filled(populated: int, empty: int, filled: int) -> pd.DataFrame:
    return pd.DataFrame({"note": ["value"] * (populated + filled) + [None] * (empty - filled)})


def test_filling_a_mostly_empty_column_is_refused_even_with_a_hint() -> None:
    before, after = _column(3, 197), _filled(3, 197, 100)

    breaches = check_invariants(before, after, _proposal(), _HINT)

    assert len(breaches) == 1
    assert "98.5% empty" in breaches[0]


def test_filling_a_mostly_populated_column_with_a_hint_is_allowed() -> None:
    before, after = _column(150, 50), _filled(150, 50, 50)

    assert check_invariants(before, after, _proposal(), _HINT) == []


def test_the_threshold_admits_a_column_exactly_half_empty() -> None:
    before, after = _column(100, 100), _filled(100, 100, 100)

    assert check_invariants(before, after, _proposal(), _HINT) == []


def test_filling_without_a_hint_is_still_refused_on_its_own_grounds() -> None:
    before, after = _column(150, 50), _filled(150, 50, 50)

    breaches = check_invariants(before, after, _proposal(), {})

    assert len(breaches) == 1
    assert "without an imputation hint" in breaches[0]


def test_a_fix_that_fills_nothing_raises_no_sparsity_complaint() -> None:
    before = _column(3, 197)

    assert check_invariants(before, before.copy(), _proposal(), _HINT) == []
