"""Pins the re-measurement the Auto Remediation node performs on every column it rewrites. The format violations and the value corrections are produced by the Format & Consistency agent one node earlier, so without this refresh the Unified agent is handed the violations the dataset carried before remediation and proposes replacements for values that no longer exist."""
from __future__ import annotations

import pandas as pd

from noipa_dq.agents.auto_remediation import (
    _drop_settled_corrections,
    _realign_range_bounds,
    _refresh_reports,
)
from noipa_dq.models import DateFormat, FormatViolation, ValidationReport

_PERIOD_SPEC = DateFormat(strftime_pattern="%Y%m")
_STALE_VALUES = {"MAR-2024": "202403", "LUG-2024": "202407"}


def _frame(values: list[str | None]) -> pd.DataFrame:
    return pd.DataFrame({"rata": values})


def _stale_report(values: list[str]) -> ValidationReport:
    return ValidationReport(
        column_name="rata",
        violations=[
            FormatViolation(
                column_name="rata",
                row_index=index,
                value=value,
                expected_pattern="date: %Y%m",
                kind="format",
            )
            for index, value in enumerate(values)
        ],
    )


def test_format_violations_settled_by_remediation_are_dropped() -> None:
    normalized = _frame(["202403", "202407", "202401"])
    refreshed = _refresh_reports(
        [_stale_report(["MAR-2024", "LUG-2024"])], normalized, {"rata"}, {"rata": _PERIOD_SPEC}, []
    )

    assert refreshed == []


def test_format_violations_still_present_are_reported_against_current_values() -> None:
    partially_normalized = _frame(["202403", "Rata 2024"])
    refreshed = _refresh_reports(
        [_stale_report(["MAR-2024", "Rata 2024"])],
        partially_normalized,
        {"rata"},
        {"rata": _PERIOD_SPEC},
        [],
    )

    assert [violation.value for violation in refreshed[0].violations] == ["Rata 2024"]


def test_untouched_columns_keep_their_format_reports() -> None:
    report = _stale_report(["MAR-2024"])
    refreshed = _refresh_reports([report], _frame(["202403"]), set(), {"rata": _PERIOD_SPEC}, [])

    assert refreshed == [report]


def test_completeness_violations_track_the_remaining_gaps() -> None:
    report = ValidationReport(
        column_name="rata",
        violations=[
            FormatViolation(
                column_name="rata",
                row_index=-1,
                value=2,
                expected_pattern="missing value",
                kind="completeness",
                affected_rows=2,
            )
        ],
    )
    refreshed = _refresh_reports([report], _frame(["202403", None]), {"rata"}, {"rata": None}, [])

    assert [violation.value for violation in refreshed[0].violations] == [1]


def test_corrections_for_rewritten_values_are_dropped() -> None:
    surviving = _drop_settled_corrections(
        {"rata": _STALE_VALUES}, _frame(["202403", "202407"]), {"rata"}
    )

    assert surviving == {}


def test_corrections_for_surviving_values_are_kept() -> None:
    surviving = _drop_settled_corrections(
        {"rata": _STALE_VALUES}, _frame(["202403", "LUG-2024"]), {"rata"}
    )

    assert surviving == {"rata": {"LUG-2024": "202407"}}


def _consistency_report(values: list[str]) -> ValidationReport:
    return ValidationReport(
        column_name="rata",
        violations=[
            FormatViolation(
                column_name="rata",
                row_index=index,
                value=value,
                expected_pattern="cross-column: aggregation-time='2024-03' implies rata='202403'",
                kind="consistency",
            )
            for index, value in enumerate(values)
        ],
    )


def test_stale_cross_column_findings_are_replaced_by_the_recomputed_pass() -> None:
    refreshed = _refresh_reports(
        [_consistency_report(["MAR-2024", "LUG-2024"])],
        _frame(["202403", "202407"]),
        {"rata"},
        {"rata": _PERIOD_SPEC},
        [],
    )

    assert refreshed == []


def test_recomputed_cross_column_findings_reach_the_refreshed_reports() -> None:
    recomputed = _consistency_report(["202401"])
    refreshed = _refresh_reports(
        [_consistency_report(["MAR-2024"])],
        _frame(["202401"]),
        {"rata"},
        {"rata": _PERIOD_SPEC},
        [recomputed],
    )

    assert [violation.value for violation in refreshed[0].violations] == ["202401"]


def test_cross_column_findings_on_untouched_columns_are_also_replaced() -> None:
    refreshed = _refresh_reports(
        [_consistency_report(["MAR-2024"])],
        _frame(["202403"]),
        set(),
        {"rata": _PERIOD_SPEC},
        [],
    )

    assert refreshed == []


def test_rounded_range_bounds_follow_the_column_they_describe() -> None:
    specs = {"spesa": {"source": "profiler", "final_spec": {
        "type": "range", "min": -12405.499999999993, "max": 12300103933.74,
    }}}

    realigned = _realign_range_bounds(specs, {"spesa": 2})

    assert realigned["spesa"]["final_spec"]["min"] == -12405.5
    assert realigned["spesa"]["final_spec"]["max"] == 12300103933.74


def test_specs_of_columns_that_were_not_rounded_are_left_alone() -> None:
    specs = {"spesa": {"final_spec": {"type": "range", "min": 0.001, "max": 1.0}}}

    assert _realign_range_bounds(specs, {}) == specs
    assert _realign_range_bounds(specs, {"altro": 2}) == specs


def test_non_range_specs_are_never_rewritten() -> None:
    specs = {"rata": {"final_spec": {"type": "date", "strftime_pattern": "%Y%m"}}}

    assert _realign_range_bounds(specs, {"rata": 2}) == specs
