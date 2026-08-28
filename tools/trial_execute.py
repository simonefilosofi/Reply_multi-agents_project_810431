"""Sandboxed dry-run for a single FixProposal: executes the proposal's code body against a copy of the dataframe, re-runs the format validator on the affected columns, checks the deterministic post-fix invariants, and returns a structured trial outcome consumed by the per-proposal self-review step in the Unified Remediation agent."""
from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd

from models import FixProposal, FormatSpec, ImputationHint, ValidationReport
from tools.fix_invariants import check_invariants
from tools.validate_format import validate_format


_MAX_DIFF_ROWS = 8


def trial_execute(
    df: pd.DataFrame,
    proposal: FixProposal,
    value_corrections: dict[str, dict[str, str | None]],
    specs_by_col: dict[str, FormatSpec | None],
    pre_reports_by_col: dict[str, ValidationReport],
    imputation_hints: dict[str, ImputationHint] | None = None,
    removable_by_column: dict[str, set] | None = None,
) -> dict:
    before = df.copy()
    hints_view = {col: h.model_dump() for col, h in (imputation_hints or {}).items()}
    try:
        wrapped = f"def clean_data(df):\n{textwrap.indent(proposal.code, '    ')}\n"
        namespace: dict = {
            "pd": pd, "np": np,
            "value_corrections": value_corrections,
            "imputation_hints": hints_view,
        }
        exec(wrapped, namespace)
        after = namespace["clean_data"](before.copy())
    except Exception as e:
        return {
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "rows_changed": 0,
            "shape_before": list(before.shape),
            "shape_after": list(before.shape),
            "diff_sample": [],
            "violation_delta": {},
            "invariant_violations": [],
        }
    if not isinstance(after, pd.DataFrame):
        return {
            "status": "error",
            "error": f"clean_data must return a DataFrame, got {type(after).__name__} (likely missing 'return df')",
            "rows_changed": 0,
            "shape_before": list(before.shape),
            "shape_after": list(before.shape),
            "diff_sample": [],
            "violation_delta": {},
            "invariant_violations": [],
        }

    rows_changed = _rows_changed(before, after, proposal.affected_columns)
    diff_sample = _diff_sample(before, after, proposal.affected_columns)
    violation_delta = _violation_delta(
        before, after, proposal.affected_columns, specs_by_col, pre_reports_by_col
    )
    return {
        "status": "applied",
        "invariant_violations": check_invariants(before, after, proposal.code, hints_view, removable_by_column),
        "rows_changed": int(rows_changed),
        "shape_before": list(before.shape),
        "shape_after": list(after.shape),
        "diff_sample": diff_sample,
        "violation_delta": violation_delta,
    }


def _rows_changed(before: pd.DataFrame, after: pd.DataFrame, cols: list[str]) -> int:
    if before.shape[0] != after.shape[0]:
        return abs(before.shape[0] - after.shape[0])
    common = [c for c in cols if c in before.columns and c in after.columns]
    if not common:
        common = list(before.columns.intersection(after.columns))
    if not common:
        return 0
    a = before[common].astype(object).where(before[common].notna(), "\x00").astype(str)
    b = after[common].astype(object).where(after[common].notna(), "\x00").astype(str)
    return int((a.values != b.values).any(axis=1).sum())


def _diff_sample(before: pd.DataFrame, after: pd.DataFrame, cols: list[str]) -> list[dict]:
    common_idx = before.index.intersection(after.index)
    affected = [c for c in cols if c in before.columns and c in after.columns]
    if not affected or common_idx.empty:
        return []
    a_block = before.loc[common_idx, affected]
    b_block = after.loc[common_idx, affected]
    a = a_block.astype(object).where(a_block.notna(), "\x00").astype(str)
    b = b_block.astype(object).where(b_block.notna(), "\x00").astype(str)
    changed_mask = (a.values != b.values).any(axis=1)
    changed_idx = common_idx[changed_mask][:_MAX_DIFF_ROWS]
    rows: list[dict] = []
    for i in changed_idx:
        row = {"_row_id": int(i)}
        for c in affected:
            bv = before.at[i, c]
            av = after.at[i, c]
            row[c] = {"before": _jsonable(bv), "after": _jsonable(av)}
        rows.append(row)
    return rows


def _violation_delta(
    before: pd.DataFrame,
    after: pd.DataFrame,
    cols: list[str],
    specs_by_col: dict[str, FormatSpec | None],
    pre_reports_by_col: dict[str, ValidationReport],
) -> dict:
    delta: dict = {}
    for col in cols:
        if col not in after.columns:
            delta[col] = {
                "format_violations_before": _format_violation_count(pre_reports_by_col.get(col)),
                "format_violations_after": None,
                "missing_before": int(before[col].isna().sum()) if col in before.columns else 0,
                "missing_after": None,
                "note": "column not present after fix",
            }
            continue
        spec = specs_by_col.get(col)
        before_count = _format_violation_count(pre_reports_by_col.get(col))
        after_report = validate_format(col, after[col], spec) if spec is not None else ValidationReport(column_name=col)
        after_count = sum(
            1 for v in after_report.violations
            if v.expected_pattern not in (None, "not nullable", "missing value")
        )
        delta[col] = {
            "format_violations_before": before_count,
            "format_violations_after": int(after_count),
            "missing_before": int(before[col].isna().sum()) if col in before.columns else 0,
            "missing_after": int(after[col].isna().sum()),
        }
    return delta


def _format_violation_count(report: ValidationReport | None) -> int:
    if report is None:
        return 0
    return sum(
        1 for v in report.violations
        if v.expected_pattern not in (None, "not nullable", "missing value")
    )


def _jsonable(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
