"""Validates each column against a FormatSpec inferred from its own values with the baseline as a hint, skipping rows an upstream node already flagged, and asks the LLM for targeted per-value corrections so the Unified agent can emit value-preserving replacements instead of generic imputations. A correction set that would delete much of a column is discarded: at that scale the inferred spec is the unreliable party. Deterministically mines functional dependencies for cross-column violations and imputation hints, over every column that actually has gaps rather than only those a spec flagged. Records the pre_remediation snapshot, the last point at which the dataset is fully measured but not yet altered, which is what the report compares the remediated result against."""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from noipa_dq.models import BaselineFile, ColumnPayload, EnumFormat, FormatViolation, ImputationHint, RangeFormat, RegexFormat, ValidationReport
from noipa_dq.state import PipelineState
from noipa_dq.tools.baseline_accessors import find_spec_by_hint
from noipa_dq.tools.duplicate_rows import duplicate_row_analysis
from noipa_dq.tools.reliability_score import checked_cells_by_column, compute_metrics, rule_counts
from noipa_dq.tools.correct_violations import correct_violations
from noipa_dq.tools.merge_reports import merge_reports
from noipa_dq.tools.arithmetic_identities import arithmetic_reports
from noipa_dq.tools.cross_column_checks import candidate_predictors, cross_column_reports
from noipa_dq.tools.infer_format_spec import infer_format_spec
from noipa_dq.tools.match_canonical import compact_format_summary
from noipa_dq.tools.mine_functional_deps import mine_functional_deps
from noipa_dq.tools.temporal_stability import is_stable, time_column
from noipa_dq.tools.profile_format_spec import profile_format_spec
from noipa_dq.tools.validate_column_names import naming_regex, validate_column_names
from noipa_dq.tools.validate_format import validate_format


_VALID_SAMPLE_SIZE = 10
_MAX_UNIQUE_OFFENDERS = 100
_EXTENDED_SAMPLE_SIZE = 150
_MAX_DELETION_SHARE = 0.02
_MAX_PREDICTOR_CARDINALITY = 0.2
_MAX_FALLBACK_PREDICTORS = 8
_MIN_FILL_RATE_FOR_IMPUTATION = 0.1


def format_consistency_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    payload_by_col = {p.column_name: p for p in state.payload}
    nullability_cols = _columns_with_nullability_violation(state.validation_reports)
    new_reports: list[ValidationReport] = _naming_reports(state)
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
        spec, source = _enforce_dtype_consistency(spec, source, payload, profiler_spec)
        inferred_specs[col] = {
            "source": source,
            "profiler_spec": profiler_spec.model_dump() if profiler_spec else None,
            "final_spec": spec.model_dump() if spec else None,
        }
        if spec is None:
            continue

        report = validate_format(col, state.dataset[col], spec)
        report.violations = _drop_already_reported(report.violations, col, state.validation_reports)
        nan_count = int(state.dataset[col].isna().sum())
        if nan_count > 0 and col not in nullability_cols:
            report.violations.append(FormatViolation(
                column_name=col, row_index=-1, value=nan_count, expected_pattern="missing value",
                kind="completeness", affected_rows=nan_count,
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
            corrections = _drop_unsafe_deletions(corrections, state.dataset[col], spec)
            if corrections:
                value_corrections[col] = corrections

    consistency_reports = cross_column_reports(
        state.dataset,
        candidate_predictors(state.payload, set(state.surviving_columns), state.dataset),
        clock=time_column(state.dataset, inferred_specs),
    ) + arithmetic_reports(state.dataset)
    merged = merge_reports(state.validation_reports, new_reports + consistency_reports)
    imputation_hints = _mine_imputation_hints(
        state.dataset, payload_by_col, merged, state.dataset, inferred_specs
    )
    pre_remediation = compute_metrics(
        state.dataset,
        merged,
        state.baseline.global_conventions if state.baseline else None,
        checked_cells=checked_cells_by_column(state.dataset, inferred_specs),
        duplicate_analysis=duplicate_row_analysis(state.dataset),
        declared_dtypes={p.column_name: p.dtype for p in state.payload if p.dtype},
    )
    pre_remediation["consistency_rules"] = rule_counts(merged)
    pre_remediation["violations_by_column"] = {
        report.column_name: sum(v.affected_rows or 1 for v in report.violations)
        for report in merged if report.violations
    }
    return state.model_copy(update={
        "validation_reports": merged,
        "value_corrections": value_corrections,
        "inferred_format_specs": inferred_specs,
        "imputation_hints": imputation_hints,
        "quality_snapshots": {**state.quality_snapshots, "pre_remediation": pre_remediation},
    })


def _drop_already_reported(
    violations: list[FormatViolation], col: str, existing: list[ValidationReport]
) -> list[FormatViolation]:
    reported_rows = {
        v.row_index
        for r in existing if r.column_name == col
        for v in r.violations if v.row_index >= 0
    }
    if not reported_rows:
        return violations
    return [v for v in violations if v.row_index not in reported_rows]


def _drop_unsafe_deletions(corrections: dict, series: pd.Series, spec) -> dict:
    deletions = [value for value, replacement in corrections.items() if replacement is None]
    if not deletions:
        return corrections
    populated = int(series.notna().sum())
    affected = int(series.astype(str).isin(deletions).sum())
    if not populated or affected / populated <= _MAX_DELETION_SHARE:
        return corrections
    return {value: replacement for value, replacement in corrections.items() if replacement is not None}


def _naming_reports(state: PipelineState) -> list[ValidationReport]:
    conventions = state.baseline.global_conventions if state.baseline else None
    pattern = naming_regex(conventions)
    return [
        ValidationReport(
            column_name=column,
            violations=[FormatViolation(
                column_name=column,
                row_index=-1,
                value=suggested,
                expected_pattern=f"naming convention: {pattern}",
                kind="schema",
            )],
        )
        for column, suggested in validate_column_names(state.surviving_columns, conventions)
    ]


def _mine_imputation_hints(
    df: pd.DataFrame,
    payload_by_col: dict[str, ColumnPayload],
    reports: list[ValidationReport],
    source: pd.DataFrame | None = None,
    specs: dict | None = None,
) -> dict[str, ImputationHint]:
    nan_columns = {
        str(c) for c in df.columns
        if df[c].isna().any() and df[c].notna().mean() > _MIN_FILL_RATE_FOR_IMPUTATION
    }
    if not nan_columns:
        return {}
    candidate_predictors = _candidate_predictors(payload_by_col, nan_columns, source)
    hints = mine_functional_deps(df, list(nan_columns), candidate_predictors)
    clock = time_column(df, specs)
    return {
        column: hint.model_copy(update={
            "temporally_stable": all(
                is_stable(df, predictor, column, clock) for predictor in hint.predictor_columns
            )
        })
        for column, hint in hints.items()
    }


def _candidate_predictors(
    payload_by_col: dict[str, ColumnPayload],
    targets: set[str],
    df: pd.DataFrame | None = None,
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
        if df is not None:
            for column in _low_cardinality_columns(df, target):
                if column not in seen:
                    candidates[target].append(column)
                    seen.add(column)
    return candidates


def _low_cardinality_columns(df: pd.DataFrame, target: str) -> list[str]:
    target_ratio = _cardinality(df, target)
    ranked = []
    for column in df.columns:
        ratio = _cardinality(df, column)
        if column == target or ratio is None or ratio > _MAX_PREDICTOR_CARDINALITY:
            continue
        distance = abs(ratio - target_ratio) if target_ratio is not None else ratio
        ranked.append((distance, column))
    return [column for _, column in sorted(ranked)[:_MAX_FALLBACK_PREDICTORS]]


def _cardinality(df: pd.DataFrame, column: str) -> float | None:
    populated = int(df[column].notna().sum())
    return df[column].nunique(dropna=True) / populated if populated else None

def _enforce_dtype_consistency(spec, source: str, payload: ColumnPayload, profiler_spec):
    dtype = (payload.dtype or "").lower()
    numeric = any(t in dtype for t in ("int", "float", "double", "decimal", "numeric"))
    temporal = any(t in dtype for t in ("date", "time"))
    if numeric and isinstance(spec, (RegexFormat, EnumFormat)):
        fallback = profiler_spec if isinstance(profiler_spec, RangeFormat) else None
        return fallback, "dtype-guard: numeric column cannot use a textual spec"
    if temporal and isinstance(spec, (RegexFormat, EnumFormat, RangeFormat)):
        return None, "dtype-guard: temporal column cannot use a textual spec"
    return spec, source


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

