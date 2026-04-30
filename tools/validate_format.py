"""Checks each value in a column against the expected format pattern from the baseline."""
from __future__ import annotations

import re

import pandas as pd

from models import BaselineFile, FormatViolation, ValidationReport


def validate_format(
    col_name: str,
    series: pd.Series,
    baseline: BaselineFile | None,
) -> ValidationReport:
    pattern: str | None = None
    if baseline:
        for domain in baseline.domains:
            for schema in domain.columns:
                if schema.column_name == col_name and schema.format_pattern:
                    pattern = schema.format_pattern
                    break

    violations: list[FormatViolation] = []
    if pattern:
        compiled = re.compile(pattern)
        for idx, val in series.items():
            if pd.notna(val) and not compiled.fullmatch(str(val)):
                violations.append(FormatViolation(
                    column_name=col_name,
                    row_index=int(idx),
                    value=val,
                    expected_pattern=pattern,
                ))

    return ValidationReport(column_name=col_name, violations=violations)
