"""Removes exact duplicate rows and records what was removed. Records colliding on a key column while carrying different data are reported rather than dropped, because discarding one of two conflicting records is a decision that needs a human. Implements the Duplicate Row agent node."""
from __future__ import annotations

from models import FormatViolation, ValidationReport
from state import PipelineState
from tools.duplicate_rows import duplicate_row_analysis


def duplicate_row_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    analysis = duplicate_row_analysis(state.dataset)
    before = len(state.dataset)
    df = state.dataset.drop_duplicates()
    analysis["rows_before"] = before
    analysis["rows_after"] = len(df)
    analysis["rows_removed"] = before - len(df)

    reports = _collision_reports(analysis)
    merged = _merge_reports(state.validation_reports, reports)
    return state.model_copy(update={
        "dataset": df,
        "duplicate_rows": analysis,
        "validation_reports": merged,
    })


def _collision_reports(analysis: dict) -> list[ValidationReport]:
    return [
        ValidationReport(
            column_name=key,
            violations=[FormatViolation(
                column_name=key,
                row_index=-1,
                value=stats["keys_with_conflicting_data"],
                expected_pattern=(
                    f"duplicate records: {stats['keys_with_conflicting_data']} values of "
                    f"{key} appear on more than one record with differing data "
                    f"(examples: {stats['examples'][:3]})"
                ),
            )],
        )
        for key, stats in analysis["key_collisions"].items()
        if stats["keys_with_conflicting_data"]
    ]


def _merge_reports(existing: list[ValidationReport], new: list[ValidationReport]) -> list[ValidationReport]:
    by_col = {r.column_name: r for r in existing}
    for report in new:
        if report.column_name in by_col:
            by_col[report.column_name].violations.extend(report.violations)
        else:
            by_col[report.column_name] = report
    return list(by_col.values())
