"""Pins the report's document builder. The point of the rewrite was that every figure is computed from the run payload and none arrives through a sentence the model wrote, so these checks assert both halves: the numbers appear where the payload puts them, and the commentary fields are carried through as text without being asked to supply any figure."""
from __future__ import annotations

from noipa_dq.tools.report_markdown import build_report_markdown

_COMMENTARY = {
    "verdict": "VERDICT TEXT",
    "schema_comment": "SCHEMA TEXT",
    "completeness_comment": "COMPLETENESS TEXT",
    "consistency_comment": "CONSISTENCY TEXT",
    "anomaly_comment": "ANOMALY TEXT",
    "remediation_comment": "REMEDIATION TEXT",
    "recommendations": ["FIRST ADVICE", "SECOND ADVICE"],
}


def _payload(**overrides) -> dict:
    payload = {
        "dataset_path": "data/spesa.csv",
        "detected_domain": "Trattamento_economico",
        "detected_language": "it",
        "shape": {"rows": 7543, "columns": 18},
        "quality": {
            "as_delivered": {
                "dimensions": ["completeness", "uniqueness"],
                "before": {"score": 0.7562, "components": {"completeness": 0.8752, "uniqueness": 0.9881}},
                "after": {"score": 0.9933, "components": {"completeness": 0.9801, "uniqueness": 1.0}},
            },
            "like_for_like": {"before": {"score": 0.938}, "after": {"score": 0.9959}},
            "dimensions_excluded": ["validity"],
            "hidden_defects_unmasked": {
                "disguised_nulls_unmasked": 988,
                "apparent_completeness": 0.8752,
                "true_completeness": 0.868,
            },
            "headline_before": {"rows": 7543, "columns": 18, "null_cells": 16939, "duplicate_rows": 40},
            "headline_after": {"rows": 7478, "columns": 11, "null_cells": 1633, "duplicate_rows": 0},
        },
        "violations_by_kind_detected": {"format": 514, "completeness": 16958, "consistency": 517,
                                       "uniqueness": 87},
        "violations_by_kind_residual": {"format": 4, "consistency": 10},
        "naming_violations": [{"column_name": "_id", "suggested_name": "id"}],
        "format_violations_detected": [{"column_name": "rata", "violation_count": 510}],
        "anomalies": [{"column_name": "spesa", "method": "iqr", "detected": 1352, "examples": [2110811.34]}],
        "duplicate_resolutions": [],
        "duplicate_rows": {"exact_duplicate_rows": 65, "rows_removed": 65,
                           "key_collisions": {"id": {"rows_in_conflicting_groups": 22}}},
        "semantic_payload": [{"column_name": "imposta", "placeholders_found": ["TBD", "n.d."]}],
        "completeness": {
            "overall": {"completeness": 0.868, "null_cells": 17927, "cells": 135774},
            "rows": {"complete_rows": 1, "rows_with_nulls": 7542},
            "by_column": {"note": {"completeness": 0.02}, "rata": {"completeness": 1.0}},
            "sparse_columns": [{"column": "note", "nulls": 7393, "null_rate": 0.98}],
        },
        "auto_remediations": [
            {"column": "rata", "operation": "normalize_period", "cells_changed": 414,
             "rationale": "alternative layouts rewritten"},
        ],
        "proposed_remediations": [
            {"id": "g2_f1", "description": "Normalise rata.", "affected_columns": ["rata"],
             "applied": True, "generated_sources": ["def clean_value(value):\n    return value"]},
            {"id": "g2_f2", "description": "Drop note.", "affected_columns": ["note"], "applied": False},
        ],
        "changes_summary": {"total_cells_changed": 5386, "by_column": {"spesa": 3088}},
    }
    payload.update(overrides)
    return payload


def test_the_document_follows_the_reader_not_the_pipeline() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)
    headings = [line for line in markdown.split("\n") if line.startswith("## ")]

    assert headings == [
        "## Verdict",
        "## The dataset as received",
        "## What the pipeline found",
        "## What was changed",
        "## The dataset as delivered",
        "## Recommendations",
    ]


def test_every_coverage_area_gets_its_own_subsection() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    for title in ("Schema validation", "Completeness", "Consistency",
                  "Anomaly detection", "Remediation"):
        assert f"### {title}" in markdown


def test_the_headline_scores_come_from_the_payload() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "**Reliability 0.756 to 0.993**" in markdown
    assert "0.938" in markdown and "0.996" in markdown


def test_counters_are_rendered_side_by_side_before_and_after() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "| null cells | 16,939 | 1,633 |" in markdown
    assert "| columns | 18 | 11 |" in markdown


def test_a_measure_absent_from_the_raw_file_is_marked_rather_than_zeroed() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "n/a" in markdown


def test_every_commentary_field_reaches_the_document() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    for text in ("VERDICT TEXT", "SCHEMA TEXT", "COMPLETENESS TEXT", "CONSISTENCY TEXT",
                 "ANOMALY TEXT", "REMEDIATION TEXT", "FIRST ADVICE", "SECOND ADVICE"):
        assert text in markdown


def test_a_generated_cleaning_function_is_printed_as_the_code_that_ran() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "```python" in markdown
    assert "def clean_value(value):" in markdown


def test_a_rejected_proposal_is_reported_as_not_applied() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "| `g2_f1` | `rata` | Normalise rata. | accepted |" in markdown
    assert "| `g2_f2` | `note` | Drop note. | not applied |" in markdown


def test_the_two_null_counts_are_explained_rather_than_left_to_collide() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "16,939" in markdown and "17,927" in markdown
    assert "counted as gaps" in markdown


def test_residual_violations_are_stated_explicitly() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert "Still open: 4 format, 10 consistency." in markdown


def test_a_clean_run_says_so_instead_of_listing_nothing() -> None:
    markdown = build_report_markdown(
        _payload(violations_by_kind_residual={"format": 0}), _COMMENTARY
    )

    assert "No violation remains in any category." in markdown


def test_the_title_names_the_file_not_its_path() -> None:
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    assert markdown.startswith("# Data Quality Report - spesa.csv")


def test_an_empty_payload_still_produces_a_document() -> None:
    markdown = build_report_markdown({}, {})

    assert markdown.startswith("# Data Quality Report")
    assert "## What was changed" not in markdown


def test_duplicate_detection_gets_its_own_row_in_the_coverage_table() -> None:
    """Exact duplicate rows were counted nowhere in the coverage table, so the one place a reader
    checks the brief's five areas showed nothing for uniqueness while sixty-five duplicate records
    had been found and removed."""
    markdown = build_report_markdown(_payload(), _COMMENTARY)

    row = next(line for line in markdown.splitlines() if line.startswith("| Duplicate detection"))

    assert "87 rows not unique when measured" in row
    assert "65 exact duplicates removed" in row
