"""Pins two ways the report described the file as better than it arrived. The coverage-area table
read the violation counts the report node happens to receive, but every remediating stage
re-measures and drops the evidence for what it fixed, so spesa - which arrived with 510 malformed
period values and 602 dates across five layouts - was reported as having had no format violations
at all. And the summary counted columns whose values were byte-identical to another's, while the
Consistency section counted the groups the duplicate-column agent actually resolved, so the same
document said one and four. Both figures now come from what the run measured."""
from __future__ import annotations

import pandas as pd

from agents.report_generator import _detected_counts
from state import PipelineState
from tools.report_markdown import _remediation_body, _unaddressed


def _state(snapshot: dict | None) -> PipelineState:
    return PipelineState(
        dataset=pd.DataFrame({"a": [1, 2, 3]}),
        quality_snapshots={"pre_remediation": snapshot} if snapshot is not None else {},
    )


def test_the_counts_come_from_before_anything_was_remediated():
    recorded = {"format": 510, "completeness": 16958, "schema": 5, "consistency": 517,
                "uniqueness": 0}

    assert _detected_counts(_state({"violations_by_kind": recorded})) == recorded


def test_the_residual_counts_are_used_when_no_snapshot_was_taken():
    counts = _detected_counts(_state(None))

    assert set(counts) == {"format", "completeness", "schema", "consistency", "uniqueness"}
    assert all(value == 0 for value in counts.values())


def test_a_snapshot_without_the_counts_falls_back_rather_than_reporting_nothing():
    counts = _detected_counts(_state({"completeness": 0.87}))

    assert counts == {"format": 0, "completeness": 0, "schema": 0, "consistency": 0,
                      "uniqueness": 0}


def test_the_unaddressed_section_names_the_column_and_the_reason():
    payload = {"unaddressed_violations": [{
        "columns": ["area_geografica"], "affected_rows": 1582,
        "reason": "no column in the dataset determines area_geografica",
    }]}

    rendered = _unaddressed(payload)

    assert "area_geografica" in rendered
    assert "1,582" in rendered
    assert "no column in the dataset determines" in rendered


def test_nothing_is_rendered_when_every_issue_has_an_action():
    assert _unaddressed({"unaddressed_violations": []}) == ""


def test_the_remediation_table_counts_what_was_carried_without_an_action():
    payload = {"unaddressed_violations": [
        {"columns": ["area_geografica"], "affected_rows": 1582, "reason": "no predictor"},
        {"columns": ["qualifica"], "affected_rows": 5086, "reason": "no predictor"},
    ]}

    body = _remediation_body(payload)

    assert "issues carried without an action" in body
    assert "Issues carried without a corrective action" in body
