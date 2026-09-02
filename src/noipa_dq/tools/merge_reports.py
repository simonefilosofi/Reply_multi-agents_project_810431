"""Combines validation reports without mutating the ones handed in. The previous helper existed in three byte-identical copies that each called .violations.extend() on a shared list, so a report merged by one node changed under the feet of any node still holding it - and the tallies read after remediation no longer described the state they were measured in."""
from __future__ import annotations

from noipa_dq.models import ValidationReport


def merge_reports(
    existing: list[ValidationReport], new: list[ValidationReport]
) -> list[ValidationReport]:
    order: list[str] = []
    collected: dict[str, list] = {}
    totals: dict[str, int | None] = {}

    for report in list(existing) + list(new):
        name = report.column_name
        if name not in collected:
            collected[name] = []
            totals[name] = None
            order.append(name)
        collected[name] = collected[name] + list(report.violations)
        if report.detected_total is not None:
            totals[name] = (totals[name] or 0) + report.detected_total

    return [
        ValidationReport(
            column_name=name,
            violations=collected[name],
            detected_total=totals[name],
        )
        for name in order
    ]
