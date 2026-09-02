"""Pins the bounding of the per-column violation payload sent to the Unified agent. A cross-column pattern names the key that implies the value, so a column carries as many distinct patterns as it has offending keys; the payload has to stay bounded without losing the total, because every violation id it contains becomes a coverage obligation on the model."""
from __future__ import annotations

import pandas as pd

from noipa_dq.agents.unified import _MAX_PATTERNS_PER_COLUMN, _aggregate_violations
from noipa_dq.models import FormatViolation, ValidationReport

_TAIL_PATTERNS = 12


def _report(distinct_patterns: int) -> ValidationReport:
    return ValidationReport(
        column_name="regione",
        violations=[
            FormatViolation(
                column_name="regione",
                row_index=index,
                value="nord",
                expected_pattern=f"cross-column: provincia='P{index}' implies regione='sud'",
                kind="consistency",
            )
            for index in range(distinct_patterns)
        ],
    )


def _frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame({"regione": ["nord"] * rows})


def test_a_handful_of_patterns_is_passed_through_unchanged() -> None:
    aggregated, _ = _aggregate_violations(0, _report(4), _frame(4), "regione")
    assert len(aggregated) == 4
    assert all(entry["count"] == 1 for entry in aggregated)


def test_a_long_tail_of_patterns_is_folded_into_one_entry_per_kind() -> None:
    total = _MAX_PATTERNS_PER_COLUMN + _TAIL_PATTERNS
    aggregated, _ = _aggregate_violations(0, _report(total), _frame(total), "regione")
    assert len(aggregated) == _MAX_PATTERNS_PER_COLUMN + 1
    assert aggregated[-1]["count"] == _TAIL_PATTERNS


def test_folding_preserves_the_total_violation_count() -> None:
    total = _MAX_PATTERNS_PER_COLUMN + _TAIL_PATTERNS
    aggregated, _ = _aggregate_violations(0, _report(total), _frame(total), "regione")
    assert sum(entry["count"] for entry in aggregated) == total


def test_every_entry_keeps_a_distinct_violation_id() -> None:
    total = _MAX_PATTERNS_PER_COLUMN + _TAIL_PATTERNS
    aggregated, _ = _aggregate_violations(0, _report(total), _frame(total), "regione")
    assert len({entry["id"] for entry in aggregated}) == len(aggregated)


def test_every_offending_row_is_still_offered_as_evidence() -> None:
    total = _MAX_PATTERNS_PER_COLUMN + _TAIL_PATTERNS
    _, row_indices = _aggregate_violations(0, _report(total), _frame(total), "regione")
    assert sorted(row_indices) == list(range(total))
