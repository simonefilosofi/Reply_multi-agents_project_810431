"""Validates column values against per-column FormatSpecs inferred from the actual sample (with baseline as a hint), flags violations, and asks an LLM to propose targeted per-value corrections so the Unified Remediation agent can emit value-preserving replace fixes instead of generic imputations. Merges new violations with reports already on state (e.g. nullability reports from the NaN handler)."""
from __future__ import annotations

import pandas as pd

from models import BaselineFile, ColumnPayload, ValidationReport
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.correct_violations import correct_violations
from tools.infer_format_spec import infer_format_spec
from tools.match_canonical import compact_format_summary
from tools.validate_format import validate_format


_VALID_SAMPLE_SIZE = 10
_MAX_UNIQUE_OFFENDERS = 100


def format_consistency_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    payload_by_col = {p.column_name: p for p in state.payload}
    new_reports: list[ValidationReport] = []
    value_corrections: dict[str, dict[str, str | None]] = {}
    for col in state.surviving_columns:
        payload = payload_by_col.get(col)
        if payload is None:
            continue
        spec = infer_format_spec(payload, _baseline_hint(state.baseline, payload))
        if spec is None:
            continue
        report = validate_format(col, state.dataset[col], spec)
        if not report.violations:
            continue
        new_reports.append(report)

        unique_offenders = list({str(v.value) for v in report.violations})[:_MAX_UNIQUE_OFFENDERS]
        expected_pattern = report.violations[0].expected_pattern or ""
        valid_sample = _valid_sample(state.dataset[col], unique_offenders)
        corrections = correct_violations(payload, expected_pattern, unique_offenders, valid_sample)
        if corrections:
            value_corrections[col] = corrections

    merged = _merge_reports(state.validation_reports, new_reports)
    return state.model_copy(update={
        "validation_reports": merged,
        "value_corrections": value_corrections,
    })


def _valid_sample(series: pd.Series, offenders: list[str]) -> list[str]:
    offender_set = set(offenders)
    valid: list[str] = []
    for v in series.dropna().unique():
        s = str(v)
        if s not in offender_set:
            valid.append(s)
        if len(valid) >= _VALID_SAMPLE_SIZE:
            break
    return valid


def _baseline_hint(baseline: BaselineFile | None, payload: ColumnPayload) -> str | None:
    if baseline is None or payload.canonical_hint == "NaN":
        return None
    schema = find_spec_by_hint(baseline, payload.canonical_hint)
    if schema is None or schema.format is None:
        return None
    return compact_format_summary(schema.format)


def _merge_reports(existing: list[ValidationReport], new: list[ValidationReport]) -> list[ValidationReport]:
    by_col: dict[str, ValidationReport] = {r.column_name: r for r in existing}
    for n in new:
        if n.column_name in by_col:
            by_col[n.column_name].violations.extend(n.violations)
        else:
            by_col[n.column_name] = n
    return list(by_col.values())
