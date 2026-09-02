"""Applies accepted FixProposals to the pipeline dataset in dependency order by executing their typed operations. A proposal is a validated sequence of catalogue operations, so remediation is deterministic and replayable; where an operation carries a generated cleaning function, that source is re-read and cleared before it runs. A proposal whose result breaks a post-fix invariant is rejected rather than applied. Returns the cleaned dataframe and a per-proposal status list (applied / skipped / error / rejected) carrying the cell-level changes each proposal produced."""
from __future__ import annotations

import numpy as np
import pandas as pd

from models import FixProposal, ImputationHint
from tools.change_log import diff_cells
from tools.fix_invariants import check_invariants
from tools.operations import apply_operations


def execute_fixes(
    df: pd.DataFrame,
    accepted: list[FixProposal],
    value_corrections: dict[str, dict[str, str | None]] | None = None,
    imputation_hints: dict[str, ImputationHint] | None = None,
    removable_by_column: dict[str, set] | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    hints_view = _hints_to_dicts(imputation_hints or {})
    ordered = _order_by_deps(accepted)
    statuses: list[dict] = []
    current = df.copy()
    applied: set[str] = set()
    applied_fingerprints: set[tuple] = set()

    for proposal in ordered:
        missing = [d for d in proposal.depends_on if d not in applied]
        if missing:
            statuses.append({"id": proposal.id, "status": "skipped", "reason": f"missing deps: {missing}"})
            continue
        fingerprint = _fingerprint(proposal)
        if fingerprint in applied_fingerprints:
            statuses.append({"id": proposal.id, "status": "skipped", "reason": "duplicate of an earlier applied fix"})
            applied.add(proposal.id)
            continue
        before = current
        try:
            result = apply_operations(current, proposal.operations, hints_view)
        except Exception as error:
            statuses.append({"id": proposal.id, "status": "error", "error": f"{type(error).__name__}: {error}"})
            current = before
            continue
        breaches = check_invariants(before, result, proposal, hints_view, removable_by_column)
        if breaches:
            statuses.append({"id": proposal.id, "status": "rejected", "invariant_violations": breaches})
            current = before
            continue
        changes, changed_cells = diff_cells(before, result, proposal.id)
        current = result
        applied.add(proposal.id)
        applied_fingerprints.add(fingerprint)
        statuses.append({
            "id": proposal.id,
            "status": "applied",
            "rows_changed": int(_rows_changed(before, current)),
            "cells_changed": changed_cells,
            "changes": changes,
            "shape_before": list(before.shape),
            "shape_after": list(current.shape),
        })
    return current, statuses


def _hints_to_dicts(hints: dict[str, ImputationHint]) -> dict[str, dict]:
    return {col: hint.model_dump() for col, hint in hints.items()}


def _fingerprint(proposal: FixProposal) -> tuple:
    return tuple(sorted(
        (operation.kind, getattr(operation, "column", ""), str(sorted(operation.model_dump().items())))
        for operation in proposal.operations
    ))


def _order_by_deps(proposals: list[FixProposal]) -> list[FixProposal]:
    by_id = {p.id: p for p in proposals}
    ordered: list[FixProposal] = []
    visited: set[str] = set()

    def visit(pid: str) -> None:
        if pid in visited or pid not in by_id:
            return
        visited.add(pid)
        for dep in by_id[pid].depends_on:
            visit(dep)
        ordered.append(by_id[pid])

    for proposal in proposals:
        visit(proposal.id)
    return ordered


def _rows_changed(before: pd.DataFrame, after: pd.DataFrame) -> int:
    if before.shape != after.shape:
        return abs(before.shape[0] - after.shape[0])
    common = before.columns.intersection(after.columns)
    if common.empty:
        return 0
    a = before[common].astype(object).where(before[common].notna(), "\x00").astype(str)
    b = after[common].astype(object).where(after[common].notna(), "\x00").astype(str)
    return int((a.values != b.values).any(axis=1).sum())
