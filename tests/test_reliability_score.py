"""Pins the deterministic quality metrics and the aggregate reliability score produced by tools/reliability_score.py. Characterisation tests hold the violation taxonomy that every consumer depends on; the strict-xfail tests state the Phase 1 target for the metrics that are currently wrong."""
from __future__ import annotations

import pandas as pd
import pytest

import tools.reliability_score as rs
from models import FormatViolation, GlobalConventions, ValidationReport


def _report(column: str, pattern: str, value=None, row_index: int = -1) -> ValidationReport:
    return ValidationReport(
        column_name=column,
        violations=[FormatViolation(
            column_name=column, row_index=row_index, value=value, expected_pattern=pattern,
        )],
    )


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "codice": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "A"],
        "importo": [1.0, 2.0, 3.0, None, 5.0, 6.0, 7.0, 8.0, 9.0, 1.0],
    })


@pytest.mark.parametrize(("pattern", "expected_kind"), [
    ("not nullable", "completeness"),
    ("missing value", "completeness"),
    ("sparse column: 96.4% null", "schema"),
    ("naming convention: ^[a-z][a-z0-9_]*(_[A-Z]{2,})?$", "schema"),
    ("duplicate-column divergence: spesa differs from its siblings on 12 cells (1.2%)", "schema"),
    ("cross-column: provincia='RM' implies regione='Lazio'", "consistency"),
    ("duplicate records: 3 keys still collide", "uniqueness"),
    ("^[0-9]{5}$", "format"),
    ("enum: ['A', 'B']", "format"),
    ("range: [0, 100]", "format"),
    ("date: %Y-%m-%d", "format"),
    ("not coercible to int64", "format"),
])
def test_every_producer_pattern_lands_in_its_bucket(pattern: str, expected_kind: str) -> None:
    counts = rs.violation_counts([_report("codice", pattern, value=1)])
    assert counts[expected_kind] == 1
    assert sum(counts.values()) == 1


def test_an_unrecognised_pattern_falls_through_to_format() -> None:
    counts = rs.violation_counts([_report("codice", "something nobody wrote a rule for")])
    assert counts["format"] == 1


def test_aggregate_completeness_violations_count_their_value_not_themselves() -> None:
    counts = rs.violation_counts([_report("codice", "missing value", value=7)])
    assert counts["completeness"] == 7


def test_a_non_numeric_aggregate_value_counts_as_one() -> None:
    counts = rs.violation_counts([_report("codice", "missing value", value="many")])
    assert counts["completeness"] == 1


def test_shape_and_completeness_come_from_the_frame() -> None:
    metrics = rs.compute_metrics(_frame())
    assert metrics["rows"] == 10
    assert metrics["columns"] == 2
    assert metrics["null_cells"] == 1
    assert metrics["completeness"] == 0.95
    assert metrics["null_by_column"] == {"codice": 0, "importo": 1}


def test_uniqueness_counts_exact_duplicate_rows() -> None:
    metrics = rs.compute_metrics(_frame())
    assert metrics["duplicate_rows"] == 1
    assert metrics["uniqueness"] == 0.9


def test_a_badly_named_column_is_a_structural_defect() -> None:
    df = pd.DataFrame({"codice_ente": [1, 2], "Codice Ente": [3, 4], "ente%code": [5, 6]})
    defects = rs.structural_defects(df, GlobalConventions())
    assert defects == {"Codice Ente": ["naming"], "ente%code": ["naming"]}


def test_an_almost_empty_column_is_a_structural_defect() -> None:
    df = pd.DataFrame({"note": [None] * 19 + ["x"], "ente": list(range(20))})
    assert rs.structural_defects(df, GlobalConventions())["note"] == ["sparse"]


def test_a_column_duplicating_another_is_a_structural_defect() -> None:
    df = pd.DataFrame({"ente": [1, 2, 3], "descrizione": ["a", "b", "c"], "ente_bis": [1, 2, 3]})
    assert rs.structural_defects(df, GlobalConventions())["ente_bis"] == ["redundant"]


def test_one_column_can_carry_several_structural_defects() -> None:
    df = pd.DataFrame({"note": [None] * 20, "Fonte Dato": [None] * 20, "ente": list(range(20))})
    assert rs.structural_defects(df, GlobalConventions())["Fonte Dato"] == [
        "naming", "sparse", "redundant",
    ]


def test_schema_conformity_is_the_share_of_columns_with_no_defect() -> None:
    df = pd.DataFrame({"codice_ente": [1, 2], "Codice Ente": [3, 4], "ente%code": [5, 6], "rata": [7, 8]})
    metrics = rs.compute_metrics(df, conventions=GlobalConventions())
    assert metrics["schema_conformity"] == 0.5
    assert metrics["columns_with_structural_defects"] == 2


def test_the_score_is_the_geometric_mean_of_the_components_present() -> None:
    scored = rs.reliability_score({"completeness": 0.9, "uniqueness": 0.7, "validity": None})
    assert set(scored["components"]) == {"completeness", "uniqueness"}
    assert scored["score"] == 0.7937


def test_one_broken_dimension_is_not_averaged_away_by_healthy_ones() -> None:
    healthy = {"completeness": 0.99, "uniqueness": 0.99, "validity": 0.99, "consistency": 0.99}
    broken = {**healthy, "schema_conformity": 0.5}
    assert rs.reliability_score(broken)["score"] < 0.88


def test_a_dimension_at_zero_zeroes_the_score() -> None:
    assert rs.reliability_score({"completeness": 0.0, "uniqueness": 1.0})["score"] == 0.0


def test_an_empty_metrics_dict_scores_to_none() -> None:
    assert rs.reliability_score({})["score"] is None


def test_ratios_are_clamped_into_the_unit_interval() -> None:
    reports = [_report("a", "^x$", 1, 0)] * 5
    metrics = rs.compute_metrics(pd.DataFrame({"a": [1, 2, 3]}), reports, checked_cells={"a": 3})
    assert metrics["validity"] == 0.0


def test_validity_divides_by_the_cells_actually_checked() -> None:
    reports = [_report("codice", "^[A-Z]$", "aa", row) for row in range(10)]
    metrics = rs.compute_metrics(_frame(), reports, checked_cells={"codice": 100})
    assert metrics["validity"] == 0.9


def test_validity_is_undefined_when_nothing_was_checked() -> None:
    metrics = rs.compute_metrics(_frame(), [_report("codice", "missing value", 1)])
    assert metrics["validity"] is None


def test_uniqueness_subtracts_rows_locked_in_a_key_conflict() -> None:
    analysis = {
        "exact_duplicate_rows": 1,
        "key_columns": ["codice"],
        "key_collisions": {"codice": {"rows_in_conflicting_groups": 4}},
    }
    metrics = rs.compute_metrics(_frame(), duplicate_analysis=analysis)
    assert metrics["uniqueness"] == 0.5


def test_a_clean_frame_has_no_structural_defects() -> None:
    metrics = rs.compute_metrics(pd.DataFrame({"ok_name": [1]}), conventions=GlobalConventions())
    assert metrics["schema_conformity"] == 1.0


def test_a_dimension_defined_on_only_one_side_is_excluded_from_both() -> None:
    before = {"completeness": 0.8, "uniqueness": 1.0, "consistency": 0.6}
    after = {"completeness": 1.0, "uniqueness": 1.0}
    compared = rs.compare(before, after)
    assert compared["dimensions"] == ["completeness", "uniqueness"]
    assert compared["before"]["score"] == 0.8944
    assert compared["after"]["score"] == 1.0


def test_checked_cells_are_reported_per_column() -> None:
    df = pd.DataFrame({"codice": ["A", None, "C"], "importo": [1.0, 2.0, 3.0], "note": [None] * 3})
    specs = {"codice": {"final_spec": {"type": "regex", "pattern": "^[A-Z]$"}},
             "importo": {"final_spec": {"type": "range", "min": 0, "max": 9}}}
    assert rs.checked_cells_by_column(df, specs) == {"codice": 2, "importo": 3}


def test_format_violations_are_reported_per_column() -> None:
    reports = [_report("codice", "^[A-Z]$", "aa", 0), _report("codice", "^[A-Z]$", "bb", 1),
               _report("importo", "range: [0, 9]", 99, 0)]
    metrics = rs.compute_metrics(_frame(), reports)
    assert metrics["format_violations_by_column"] == {"codice": 2, "importo": 1}


def test_inconsistent_rows_are_reported_per_column_without_double_counting() -> None:
    pattern = "cross-column: a=1 implies b=2"
    reports = [_report("regione", pattern, "x", 0), _report("regione", pattern, "y", 0),
               _report("regione", pattern, "z", 1), _report("qualifica", pattern, "w", 0)]
    metrics = rs.compute_metrics(_frame(), reports)
    assert metrics["inconsistent_rows_by_column"] == {"regione": 2, "qualifica": 1}
    assert metrics["inconsistent_rows"] == 2
