"""Validates column values against per-column FormatSpecs inferred from the actual sample (with baseline as a hint), flags violations, asks an LLM to propose targeted per-value corrections so the Unified Remediation agent can emit value-preserving replace fixes instead of generic imputations, and deterministically mines functional dependencies between related columns to surface NaN-imputation hints (lookup mappings) for the Unified agent. Merges new violations with reports already on state (e.g. nullability reports from the NaN handler)."""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from models import BaselineFile, ColumnPayload, FormatViolation, ImputationHint, ValidationReport
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.correct_violations import correct_violations
from tools.infer_format_spec import infer_format_spec
from tools.match_canonical import compact_format_summary
from tools.mine_functional_deps import mine_functional_deps
from tools.profile_format_spec import profile_format_spec
from tools.validate_format import validate_format


_VALID_SAMPLE_SIZE = 10
_MAX_UNIQUE_OFFENDERS = 100
_EXTENDED_SAMPLE_SIZE = 150


def format_consistency_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    payload_by_col = {p.column_name: p for p in state.payload}
    nullability_cols = _columns_with_nullability_violation(state.validation_reports)
    new_reports: list[ValidationReport] = []
    value_corrections: dict[str, dict[str, str | None]] = {}
    inferred_specs: dict[str, dict] = {}
    for col in state.surviving_columns:
        payload = payload_by_col.get(col)
        if payload is None:
            continue
        profiler_spec = profile_format_spec(state.dataset[col])
        extended_sample = _extended_unique_sample(state.dataset[col])
        llm_spec = infer_format_spec(
            payload,
            _baseline_hint(state.baseline, payload),
            candidate=profiler_spec,
            extended_sample=extended_sample,
        )
        spec, source = _resolve_spec(profiler_spec, llm_spec)
        inferred_specs[col] = {
            "source": source,
            "profiler_spec": profiler_spec.model_dump() if profiler_spec else None,
            "final_spec": spec.model_dump() if spec else None,
        }
        if spec is None:
            continue

        report = validate_format(col, state.dataset[col], spec)
        nan_count = int(state.dataset[col].isna().sum())
        if nan_count > 0 and col not in nullability_cols:
            report.violations.append(FormatViolation(
                column_name=col, row_index=-1, value=nan_count, expected_pattern="missing value",
            ))
        if not report.violations:
            continue
        new_reports.append(report)

        format_violations = [v for v in report.violations if v.expected_pattern != "missing value"]
        if format_violations:
            unique_offenders = list({str(v.value) for v in format_violations})[:_MAX_UNIQUE_OFFENDERS]
            expected_pattern = format_violations[0].expected_pattern or ""
            valid_sample = _valid_sample(state.dataset[col], unique_offenders)
            corrections = correct_violations(payload, expected_pattern, unique_offenders, valid_sample)
            if corrections:
                value_corrections[col] = corrections

    merged = _merge_reports(state.validation_reports, new_reports)
    imputation_hints = _mine_imputation_hints(state.dataset, payload_by_col, merged)
    return state.model_copy(update={
        "validation_reports": merged,
        "value_corrections": value_corrections,
        "inferred_format_specs": inferred_specs,
        "imputation_hints": imputation_hints,
    })


def _mine_imputation_hints(
    df: pd.DataFrame,
    payload_by_col: dict[str, ColumnPayload],
    reports: list[ValidationReport],
) -> dict[str, ImputationHint]:
    nan_columns = _columns_with_nan_violations(reports)
    if not nan_columns:
        return {}
    candidate_predictors = _candidate_predictors(payload_by_col, nan_columns)
    return mine_functional_deps(df, list(nan_columns), candidate_predictors)


def _columns_with_nan_violations(reports: list[ValidationReport]) -> set[str]:
    flagged: set[str] = set()
    for r in reports:
        for v in r.violations:
            if v.expected_pattern in ("missing value", "not nullable"):
                flagged.add(r.column_name)
                break
    return flagged


def _candidate_predictors(
    payload_by_col: dict[str, ColumnPayload], targets: set[str]
) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = defaultdict(list)
    for target in targets:
        payload = payload_by_col.get(target)
        if payload is None:
            continue
        seen: set[str] = set()
        for r in payload.related_columns:
            if r != target and r not in seen:
                candidates[target].append(r)
                seen.add(r)
    return candidates


def _resolve_spec(profiler_spec, llm_spec):
    if profiler_spec is None and llm_spec is None:
        return None, "skipped"
    if profiler_spec is None:
        return llm_spec, "llm-only"
    if llm_spec is None or llm_spec == profiler_spec:
        return profiler_spec, "deterministic"
    return llm_spec, "deterministic-refined"


def _columns_with_nullability_violation(reports: list[ValidationReport]) -> set[str]:
    return {
        r.column_name for r in reports
        if any(v.expected_pattern == "not nullable" for v in r.violations)
    }


def _extended_unique_sample(series: pd.Series) -> list:
    non_null = series.dropna()
    if non_null.empty:
        return []
    uniques = non_null.unique().tolist()
    return uniques[:_EXTENDED_SAMPLE_SIZE]


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
