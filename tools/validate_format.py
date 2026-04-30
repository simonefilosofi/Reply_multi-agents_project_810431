"""Checks each value in a column against the expected regex format pattern from the baseline. Step-1 compatibility shim: only RegexFormat specs are honoured here; enum and range dispatch land in step 6 (Format & Consistency)."""
from __future__ import annotations

import re

import pandas as pd

from models import BaselineFile, FormatViolation, RegexFormat, ValidationReport


def validate_format(
    col_name: str,
    series: pd.Series,
    baseline: BaselineFile | None,
) -> ValidationReport:
    pattern = _lookup_regex_pattern(baseline, col_name)
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


def _lookup_regex_pattern(baseline: BaselineFile | None, col_name: str) -> str | None:
    if baseline is None:
        return None
    for domain in baseline.domains.values():
        for dataset in domain.datasets.values():
            schema = dataset.columns.get(col_name)
            if schema and isinstance(schema.format, RegexFormat):
                return schema.format.pattern
    return None
