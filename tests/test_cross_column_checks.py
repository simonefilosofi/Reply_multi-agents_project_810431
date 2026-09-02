"""Pins the mined functional-dependency check that feeds the consistency dimension: a dependency that always holds raises nothing, a dependency broken on a few rows raises exactly those rows, and a dependency that shifts over time is left alone. Also pins that detection is complete and that a row condemned by several predictors is reported once, so the consistency count is a row count."""
from __future__ import annotations

import pandas as pd

from noipa_dq.tools.cross_column_checks import cross_column_reports

_PURE_GROUPS = {"P1": "nord", "P2": "nord", "P3": "sud", "P4": "sud",
                "P5": "centro", "P6": "centro", "P7": "isole", "P8": "isole"}
_DRIFTING_ROWS = 3


def _frame(drifting: bool) -> pd.DataFrame:
    rows = [
        {"provincia": "P0", "regione": "nord" if drifting else "sud", "anno": 2023, "protocollo": f"X{i}"}
        for i in range(_DRIFTING_ROWS)
    ]
    rows += [
        {"provincia": "P0", "regione": "sud", "anno": 2024, "protocollo": f"Y{i}"}
        for i in range(4)
    ]
    for province, regione in _PURE_GROUPS.items():
        rows += [
            {"provincia": province, "regione": regione, "anno": 2023 + (i % 2), "protocollo": f"{province}{i}"}
            for i in range(5)
        ]
    return pd.DataFrame(rows)


def _reports(df: pd.DataFrame, clock: str | None = None):
    return cross_column_reports(df, {"regione": ["provincia"]}, clock=clock)


def test_a_dependency_that_always_holds_raises_nothing() -> None:
    assert _reports(_frame(drifting=False)) == []


def test_a_dependency_broken_on_a_few_rows_raises_exactly_those_rows() -> None:
    reports = _reports(_frame(drifting=True))
    assert len(reports) == 1
    assert reports[0].column_name == "regione"
    assert {v.row_index for v in reports[0].violations} == set(range(_DRIFTING_ROWS))


def test_the_violation_names_the_predictor_and_the_value_it_implies() -> None:
    violation = _reports(_frame(drifting=True))[0].violations[0]
    assert violation.expected_pattern.startswith("cross-column: ")
    assert "provincia='P0'" in violation.expected_pattern
    assert "regione='sud'" in violation.expected_pattern
    assert violation.value == "nord"


def test_a_dependency_that_shifts_over_time_is_left_alone() -> None:
    assert _reports(_frame(drifting=True), clock="anno") == []


def test_a_near_unique_column_is_never_used_as_a_predictor() -> None:
    df = _frame(drifting=True)
    assert cross_column_reports(df, {"regione": ["protocollo"]}) == []


def test_detection_is_not_truncated() -> None:
    reports = _reports(_frame(drifting=True))
    assert len(reports[0].violations) == _DRIFTING_ROWS


def test_a_row_is_reported_once_however_many_predictors_condemn_it() -> None:
    df = _frame(drifting=True)
    df["provincia_bis"] = df["provincia"]
    reports = cross_column_reports(df, {"regione": ["provincia", "provincia_bis"]})
    row_indices = [v.row_index for v in reports[0].violations]
    assert sorted(row_indices) == list(range(_DRIFTING_ROWS))
