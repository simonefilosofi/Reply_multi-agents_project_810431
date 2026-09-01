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


def test_the_unaddressed_section_names_each_column_with_its_own_count():
    payload = {"unaddressed_violations": [{
        "columns": ["area_geografica", "qualifica"],
        "affected_by_column": {"area_geografica": 1582, "qualifica": 5086},
        "reason": "no column in the dataset determines them",
    }]}

    rendered = _unaddressed(payload)

    assert "`area_geografica` (1,582)" in rendered
    assert "`qualifica` (5,086)" in rendered
    assert "6,668" not in rendered, "per-column counts overlap and must not be summed"


def test_a_column_taken_over_by_a_proposal_is_named_as_such():
    payload = {"unaddressed_violations": [{
        "columns": ["area_geografica"], "affected_by_column": {"area_geografica": 1582},
        "actioned_elsewhere": ["note", "fonte_dato"],
        "reason": "note and fonte_dato cannot be filled",
    }]}

    rendered = _unaddressed(payload)

    assert "`note`" in rendered and "covered by a proposal" in rendered


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


def test_the_cross_column_rules_are_listed_with_before_and_after():
    from tools.report_markdown import _cross_column_rules

    payload = {"cross_column_rules": [
        {"rule": "saldo = trasferimenti_in - trasferimenti_out",
         "rows_breaking": 648, "rows_remaining": 648},
        {"rule": "cod_imposta determines imposta", "rows_breaking": 12, "rows_remaining": 0},
    ]}

    rendered = _cross_column_rules(payload)

    assert "saldo = trasferimenti_in - trasferimenti_out" in rendered
    assert "648" in rendered
    assert "cod_imposta determines imposta" in rendered


def test_no_rule_table_is_printed_when_none_were_checked():
    from tools.report_markdown import _cross_column_rules

    assert _cross_column_rules({"cross_column_rules": []}) == ""


def test_the_two_duplicate_row_counts_are_reconciled():
    from tools.report_markdown import _duplicate_row_note

    payload = {"quality": {"headline_before": {"duplicate_rows": 40}},
               "duplicate_rows": {"rows_removed": 65}}

    note = _duplicate_row_note(payload)

    assert "40" in note and "65" in note
    assert "not a discrepancy" in note


def test_nothing_is_reconciled_when_the_counts_agree():
    from tools.report_markdown import _duplicate_row_note

    payload = {"quality": {"headline_before": {"duplicate_rows": 65}},
               "duplicate_rows": {"rows_removed": 65}}

    assert _duplicate_row_note(payload) == ""


def test_a_single_duplicate_group_is_not_described_in_the_plural():
    from tools.report_markdown import _fault_table

    rendered = _fault_table({
        "violations_by_kind_detected": {"consistency": 1},
        "duplicate_resolutions": [{"canonical_name": "codice_amministrazione"}],
    })

    assert "1 duplicate column group " in rendered or "1 duplicate column group|" in rendered.replace(" |", "|")
    assert "1 duplicate column groups" not in rendered
    assert "1 cross-column violations" not in rendered


def test_the_per_column_table_lists_every_column():
    from tools.report_markdown import _per_column

    payload = {"per_column": [
        {"column": "spesa", "from": "SPESA TOTALE", "dtype": "float64", "fill_rate": 0.992,
         "detected": 59, "outstanding": 0, "cells_changed": 2878},
        {"column": "rata", "from": "", "dtype": "int64", "fill_rate": 1.0,
         "detected": 510, "outstanding": 0, "cells_changed": 510},
    ]}

    rendered = _per_column(payload)

    assert "`spesa`" in rendered and "from SPESA TOTALE" in rendered
    assert "99.2%" in rendered
    assert "2,878" in rendered
    assert "`rata`" in rendered


def test_several_columns_taken_over_are_named_in_the_plural():
    from tools.report_markdown import _actioned_note

    single = _actioned_note({"actioned_elsewhere": ["note"]})
    several = _actioned_note({"actioned_elsewhere": ["note", "fonte_dato"]})

    assert "`note` is also named" in single
    assert "are also named" in several and "are covered" in several


def test_a_rule_over_a_renamed_column_is_matched_across_the_rename():
    from agents.report_generator import _rule_under_original_names

    origins = {"rata": "RATA", "id": "_id"}

    assert _rule_under_original_names("rata determines mese", origins) == "RATA determines mese"
    assert _rule_under_original_names("saldo = a - b", origins) == "saldo = a - b"


def test_a_column_that_kept_its_name_is_left_alone():
    from agents.report_generator import _rule_under_original_names

    assert _rule_under_original_names(
        "cod_imposta determines imposta", {"imposta": "imposta"}
    ) == "cod_imposta determines imposta"
