"""Applies the FixProposals approved at the human gate through the local executor, keeps the payload and the inferred specs aligned with any column a fix renamed or dropped, then collapses values left differing only by casing or whitespace and re-applies the proposed dtype. Those two passes are automatic cleaning rather than remediation, so they run whether or not a fix was approved: remediation may have removed exactly the values that blocked a cast upstream. Records which fix ids landed and surfaces on state.errors every approved fix that did not, whether it errored, breached an invariant, or was skipped."""
from __future__ import annotations

import pandas as pd

from noipa_dq.models import EnumFormat, FormatSpec
from noipa_dq.state import PipelineState
from noipa_dq.tools.apply_casing import collapse_casing_variants
from noipa_dq.tools.change_log import diff_cells
from noipa_dq.tools.execute_fixes import execute_fixes
from noipa_dq.tools.safe_cast import safe_cast
from noipa_dq.tools.fix_invariants import removable_values


def apply_fixes_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    approved_ids = set(state.approved_fix_ids)
    approved = [p for p in state.proposed_fixes if p.id in approved_ids]
    statuses: list[dict] = []
    cleaned = state.dataset

    if approved:
        cleaned, statuses = execute_fixes(
            state.dataset,
            approved,
            state.value_corrections,
            imputation_hints=state.imputation_hints,
            removable_by_column=removable_values(state.payload, state.validation_reports),
        )

    after_fixes = cleaned
    cleaned = _collapse_casing(cleaned.copy(), state)
    casing_changes, _ = diff_cells(after_fixes, cleaned, "collapse_casing")
    before_cast = cleaned.copy()
    cleaned = _enforce_dtypes(cleaned.copy(), state)
    cast_changes, _ = diff_cells(before_cast, cleaned, "enforce_dtype")
    failures = [
        f"apply_fixes:{s['id']}: {_failure_detail(s)}"
        for s in statuses
        if s["status"] in ("error", "rejected", "skipped")
    ]
    renames = {
        operation.column: operation.new_name
        for proposal in approved
        if proposal.id in {status["id"] for status in statuses if status["status"] == "applied"}
        for operation in proposal.operations
        if operation.kind == "rename_column" and operation.new_name
    }
    change_log = state.change_log + [
        change
        for status in statuses
        for change in status.get("changes", [])
    ] + casing_changes + cast_changes
    return state.model_copy(update={
        "dataset": cleaned,
        "payload": _realign_payload(state.payload, cleaned.columns, renames),
        "surviving_columns": list(cleaned.columns),
        "inferred_format_specs": _realign_specs(state.inferred_format_specs, cleaned.columns, renames),
        "change_log": change_log,
        "applied_fix_ids": [s["id"] for s in statuses if s["status"] == "applied"],
        "errors": state.errors + failures,
    })


def _failure_detail(status: dict) -> str:
    """Why an approved fix did not land. A skip used to be silent, so a proposal the reviewer had
    accepted could vanish between the gate and the dataset with nothing in state.errors to say
    so; the only trace was a count that did not add up."""
    return str(
        status.get("error")
        or status.get("invariant_violations")
        or status.get("reason")
        or status["status"]
    )


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


def _realign_payload(payload, columns, renames: dict[str, str]):
    present = set(columns)
    realigned = []
    for entry in payload:
        name = renames.get(entry.column_name, entry.column_name)
        if name not in present:
            continue
        realigned.append(entry.model_copy(update={
            "column_name": name,
            "related_columns": [
                renames.get(c, c) for c in entry.related_columns if renames.get(c, c) in present
            ],
        }))
    return realigned


def _realign_specs(specs: dict, columns, renames: dict[str, str]) -> dict:
    present = set(columns)
    return {
        renames.get(column, column): spec
        for column, spec in specs.items()
        if renames.get(column, column) in present
    }
