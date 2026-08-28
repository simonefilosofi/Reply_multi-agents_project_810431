"""Applies the FixProposals approved at the human gate to the pipeline dataset via the local executor, then deterministically collapses any values left differing only by casing or whitespace and re-applies the dtype proposed by the Semantic agent, since remediation may have removed exactly the values that blocked the cast upstream, recording which fix ids landed and surfacing executor failures on state.errors. Implements the Apply step between the Unified Remediation agent and the final duplicate-row pass."""
from __future__ import annotations

import pandas as pd

from models import EnumFormat, FormatSpec
from state import PipelineState
from tools.apply_casing import collapse_casing_variants
from tools.execute_fixes import execute_fixes
from tools.safe_cast import safe_cast
from tools.fix_invariants import removable_values


def apply_fixes_node(state: PipelineState) -> PipelineState:
    if state.dataset is None or not state.approved_fix_ids:
        return state

    approved_ids = set(state.approved_fix_ids)
    approved = [p for p in state.proposed_fixes if p.id in approved_ids]
    if not approved:
        return state

    cleaned, statuses = execute_fixes(
        state.dataset,
        approved,
        state.value_corrections,
        imputation_hints=state.imputation_hints,
        removable_by_column=removable_values(state.payload, state.validation_reports),
    )

    cleaned = _collapse_casing(cleaned, state)
    cleaned = _enforce_dtypes(cleaned, state)
    failures = [
        f"apply_fixes:{s['id']}: {s.get('error') or s.get('invariant_violations')}"
        for s in statuses
        if s["status"] in ("error", "rejected")
    ]
    return state.model_copy(update={
        "dataset": cleaned,
        "applied_fix_ids": [s["id"] for s in statuses if s["status"] == "applied"],
        "errors": state.errors + failures,
    })


def _enforce_dtypes(df: pd.DataFrame, state: PipelineState) -> pd.DataFrame:
    for column in state.payload:
        name = column.column_name
        if name not in df.columns or not column.dtype:
            continue
        if column.dtype == str(df[name].dtype):
            continue
        cast, blocking = safe_cast(df[name], column.dtype)
        if not blocking:
            df[name] = cast
    return df


def _collapse_casing(df: pd.DataFrame, state: PipelineState) -> pd.DataFrame:
    for column in df.columns:
        df[column] = collapse_casing_variants(df[column], _enum_spec(state, column))
    return df


def _enum_spec(state: PipelineState, column: str) -> FormatSpec | None:
    info = state.inferred_format_specs.get(column) or {}
    spec = info.get("final_spec")
    if not spec or spec.get("type") != "enum":
        return None
    return EnumFormat(**spec)
