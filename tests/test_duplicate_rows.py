"""Pins the row-level duplicate analysis behind the uniqueness metric and the Duplicate Row agent: which columns are elected as keys, what counts as an exact duplicate, and the difference between a key that merely repeats and a key that repeats while carrying different data."""
from __future__ import annotations

import numpy as np
import pandas as pd

from noipa_dq.tools.duplicate_rows import duplicate_row_analysis, key_columns

_ROWS = 40


def _frame(last_row: dict) -> pd.DataFrame:
    body = [
        {"id": f"K{i}", "stato": "attivo" if i % 2 else "cessato", "valore": i % 4, "note": np.nan}
        for i in range(_ROWS - 1)
    ]
    return pd.DataFrame(body + [last_row])


def _distinct_last_row() -> dict:
    return {"id": "K39", "stato": "attivo", "valore": 3, "note": np.nan}


def _colliding_last_row() -> dict:
    return {"id": "K0", "stato": "attivo", "valore": 3, "note": np.nan}


def _repeated_last_row() -> dict:
    return {"id": "K0", "stato": "cessato", "valore": 0, "note": np.nan}


def test_only_the_near_unique_column_is_elected_as_a_key() -> None:
    assert key_columns(_frame(_distinct_last_row())) == ["id"]


def test_an_entirely_empty_column_is_never_a_key() -> None:
    assert "note" not in key_columns(_frame(_distinct_last_row()))


def test_a_frame_of_distinct_rows_reports_no_duplicates() -> None:
    analysis = duplicate_row_analysis(_frame(_distinct_last_row()))
    assert analysis["exact_duplicate_rows"] == 0
    assert analysis["key_collisions"] == {}


def test_a_key_repeated_with_different_data_is_a_conflict_not_a_duplicate() -> None:
    analysis = duplicate_row_analysis(_frame(_colliding_last_row()))
    assert analysis["exact_duplicate_rows"] == 0
    assert analysis["key_collisions"]["id"]["duplicated_keys"] == 1
    assert analysis["key_collisions"]["id"]["affected_rows"] == 2
    assert analysis["key_collisions"]["id"]["keys_with_conflicting_data"] == 1
    assert analysis["key_collisions"]["id"]["examples"] == ["K0"]


def test_a_repeated_key_carrying_identical_data_is_a_duplicate_not_a_conflict() -> None:
    analysis = duplicate_row_analysis(_frame(_repeated_last_row()))
    assert analysis["exact_duplicate_rows"] == 1
    assert analysis["key_collisions"]["id"]["duplicated_keys"] == 1
    assert analysis["key_collisions"]["id"]["keys_with_conflicting_data"] == 0


def test_duplicated_keys_survive_deduplication_only_when_they_conflict() -> None:
    deduplicated = _frame(_repeated_last_row()).drop_duplicates()
    residual = duplicate_row_analysis(deduplicated)
    assert residual["key_collisions"] == {}


def test_a_collision_reports_how_many_rows_it_locks_up() -> None:
    analysis = duplicate_row_analysis(_frame(_colliding_last_row()))
    assert analysis["key_collisions"]["id"]["rows_in_conflicting_groups"] == 2
