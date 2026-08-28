"""Applies the FixProposals approved at the human gate to the pipeline dataset via the local executor, recording which fix ids landed and surfacing executor failures on state.errors. Implements the Apply step between the Unified Remediation agent and the final duplicate-row pass."""
from __future__ import annotations

from state import PipelineState
from tools.execute_fixes import execute_fixes


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
    )

    failures = [f"apply_fixes:{s['id']}: {s['error']}" for s in statuses if s["status"] == "error"]
    return state.model_copy(update={
        "dataset": cleaned,
        "applied_fix_ids": [s["id"] for s in statuses if s["status"] == "applied"],
        "errors": state.errors + failures,
    })
