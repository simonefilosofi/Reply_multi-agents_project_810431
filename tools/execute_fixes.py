"""Locally executes accepted FixProposal code bodies against the pipeline dataset, in dependency order. Each proposal's `code` is wrapped as the body of clean_data(df) and invoked in a namespace exposing pd, np, and the per-column value_corrections map promised by the unified prompt. A proposal whose result breaks a deterministic post-fix invariant is rejected rather than applied. Returns the cleaned dataframe and a per-proposal status list (applied / skipped / error / rejected)."""
from __future__ import annotations

import textwrap

import numpy as np
import pandas as pd

from models import FixProposal, ImputationHint
from tools.fix_invariants import check_invariants


def execute_fixes(
    df: pd.DataFrame,
    accepted: list[FixProposal],
    value_corrections: dict[str, dict[str, str | None]],
    imputation_hints: dict[str, ImputationHint] | None = None,
    removable_by_column: dict[str, set] | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    hints_view = _hints_to_dicts(imputation_hints or {})
    ordered = _order_by_deps(accepted)
    statuses: list[dict] = []
    current = df.copy()
    applied: set[str] = set()
    applied_fingerprints: set[tuple] = set()
    for p in ordered:
        missing = [d for d in p.depends_on if d not in applied]
        if missing:
            statuses.append({"id": p.id, "status": "skipped", "reason": f"missing deps: {missing}"})
            continue
        fp = _fingerprint(p)
        if fp in applied_fingerprints:
            statuses.append({"id": p.id, "status": "skipped", "reason": "duplicate of an earlier applied fix"})
            applied.add(p.id)
            continue
        before = current
        try:
            wrapped = f"def clean_data(df):\n{textwrap.indent(p.code, '    ')}\n"
            namespace: dict = {
                "pd": pd, "np": np,
                "value_corrections": value_corrections,
                "imputation_hints": hints_view,
            }
            exec(wrapped, namespace)
            result = namespace["clean_data"](current.copy())
        except Exception as e:
            statuses.append({"id": p.id, "status": "error", "error": f"{type(e).__name__}: {e}"})
            current = before
            continue
        if not isinstance(result, pd.DataFrame):
            statuses.append({
                "id": p.id,
                "status": "error",
                "error": f"clean_data must return a DataFrame, got {type(result).__name__} (likely missing 'return df')",
            })
            current = before
            continue
        breaches = check_invariants(before, result, p.code, hints_view, removable_by_column)
        if breaches:
            statuses.append({"id": p.id, "status": "rejected", "invariant_violations": breaches})
            current = before
            continue
        current = result
        applied.add(p.id)
        applied_fingerprints.add(fp)
        statuses.append({
            "id": p.id,
            "status": "applied",
            "rows_changed": int(_rows_changed(before, current)),
            "shape_before": list(before.shape),
            "shape_after": list(current.shape),
        })
    return current, statuses


def _hints_to_dicts(hints: dict[str, ImputationHint]) -> dict[str, dict]:
    return {col: hint.model_dump() for col, hint in hints.items()}


def _fingerprint(p: FixProposal) -> tuple:
    return (
        frozenset(p.affected_columns),
        frozenset(p.addresses_violations),
        "\n".join(line.strip() for line in p.code.splitlines() if line.strip()),
    )


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

    for p in proposals:
        visit(p.id)
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
