"""Pins the cardinality guard on inferred enums. An enum admits only its common values and reports the tail, which is the defect on a closed vocabulary and the subject matter on a column of proper nouns. Without the guard, attivazioniCessazioni produced an enum of the 13 most frequent public bodies out of 98 real ones, declared 1905 rows invalid, and the remediation stage - asked to make those values conform - proposed rewriting C.N.E.L. into CORTE DEI CONTI."""
from __future__ import annotations

import pandas as pd

from models import EnumFormat
from tools.profile_format_spec import _MAX_ENUM, profile_format_spec


def _column(values: dict[str, int]) -> pd.Series:
    return pd.Series([value for value, count in values.items() for _ in range(count)])


def test_a_closed_vocabulary_with_a_defective_tail_stays_an_enum() -> None:
    column = _column({
        "Erariali": 2775, "Varie": 2206, "Previdenziali": 1629, "Netto": 804,
        "Assistenziali": 121, "erariali": 1, "ERARIALI": 1, "Erariali ": 2, "Da definire": 2,
    })

    spec = profile_format_spec(column)

    assert isinstance(spec, EnumFormat)
    assert "erariali" not in spec.values
    assert "Erariali" in spec.values


def test_a_directory_of_proper_nouns_is_not_an_enum() -> None:
    frequent = {f"MINISTERO {index}": 300 for index in range(13)}
    tail = {f"ENTE MINORE {index}": 20 for index in range(85)}

    spec = profile_format_spec(_column({**frequent, **tail}))

    assert not isinstance(spec, EnumFormat)


def test_the_guard_counts_every_distinct_value_not_only_the_frequent_ones() -> None:
    dominant = {"A": 500, "B": 500}
    tail = {f"rare {index}": 1 for index in range(_MAX_ENUM)}

    assert isinstance(profile_format_spec(_column(dominant)), EnumFormat)
    assert not isinstance(profile_format_spec(_column({**dominant, **tail})), EnumFormat)


def test_a_column_exactly_at_the_limit_is_still_admitted() -> None:
    values = {f"value {index}": 100 for index in range(_MAX_ENUM)}

    assert isinstance(profile_format_spec(_column(values)), EnumFormat)


def test_a_column_one_past_the_limit_is_not() -> None:
    values = {f"value {index}": 100 for index in range(_MAX_ENUM + 1)}

    assert not isinstance(profile_format_spec(_column(values)), EnumFormat)
