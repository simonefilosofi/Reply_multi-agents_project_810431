"""Proposal-only Unified remediation agent: groups columns by related_columns transitive closure, aggregates upstream validation_reports into IDed violations per column, builds a per-group LLM payload (columns + evidence rows + clean reference rows), invokes structured FixGroupResponse output, runs coverage checks with one retry, and writes group-prefixed proposals to state.proposed_fixes. Does NOT execute any code; downstream nodes own approval and sandboxed execution."""
from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd
from langchain_openai import ChatOpenAI

from models import ColumnPayload, FixGroupResponse, FixProposal, ValidationReport
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.match_canonical import compact_format_summary
from utils.prompts import load_prompt


_MAX_EVIDENCE_ROWS = 10
_MAX_CLEAN_ROWS = 5
_EXAMPLES_PER_VIOLATION = 3
_CORRECTION_EXAMPLES = 20


def unified_node(state: PipelineState) -> PipelineState:
    if state.dataset is None or not state.payload:
        return state

    payload_by_name = {p.column_name: p for p in state.payload}
    reports_by_name = {r.column_name: r for r in state.validation_reports}
    groups = _build_groups(state.payload)

    actionable = [g for g in groups if any(reports_by_name.get(c, _empty_report(c)).violations for c in g)]
    if not actionable:
        return state.model_copy(update={"proposed_fixes": [], "fix_groups": {}})

    all_proposals: list[FixProposal] = []
    fix_groups: dict[str, list[str]] = {}
    for group_idx, group in enumerate(actionable):
        group_id = f"g{group_idx + 1}"
        fix_groups[group_id] = group
        all_proposals.extend(propose_for_group(
            group_id, group, payload_by_name, reports_by_name, state.dataset, state.baseline,
            value_corrections=state.value_corrections,
        ))

    return state.model_copy(update={"proposed_fixes": all_proposals, "fix_groups": fix_groups})


def propose_for_group(
    group_id: str,
    group: list[str],
    payload_by_name: dict[str, ColumnPayload],
    reports_by_name: dict[str, ValidationReport],
    df: pd.DataFrame,
    baseline,
    value_corrections: dict[str, dict[str, str | None]] | None = None,
    feedback: str = "",
) -> list[FixProposal]:
    chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0).with_structured_output(FixGroupResponse)
    system = load_prompt("unified")
    ctx, input_violation_ids = _build_group_context(
        group_id, group, payload_by_name, reports_by_name, df, baseline, value_corrections or {}
    )
    if feedback:
        ctx["user_feedback_on_previous_response"] = feedback
    response = _invoke_with_retry(chain, system, ctx, input_violation_ids, group)
    if response is None:
        return []
    return [_namespace_proposal(group_id, p) for p in response.proposals]


def _build_groups(payload: list[ColumnPayload]) -> list[list[str]]:
    parent: dict[str, str] = {p.column_name: p.column_name for p in payload}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for p in payload:
        for related in p.related_columns:
            if related in parent:
                union(p.column_name, related)

    grouped: dict[str, list[str]] = defaultdict(list)
    for p in payload:
        grouped[find(p.column_name)].append(p.column_name)
    return list(grouped.values())


def _build_group_context(
    group_id: str,
    group: list[str],
    payload_by_name: dict[str, ColumnPayload],
    reports_by_name: dict[str, ValidationReport],
    df: pd.DataFrame,
    baseline,
    value_corrections: dict[str, dict[str, str | None]],
) -> tuple[dict, set[str]]:
    columns_payload: list[dict] = []
    input_violation_ids: set[str] = set()
    violation_row_indices: set[int] = set()

    for col_idx, col in enumerate(group):
        p = payload_by_name.get(col)
        if p is None:
            continue
        report = reports_by_name.get(col)
        spec = find_spec_by_hint(baseline, p.canonical_hint) if baseline and p.canonical_hint != "NaN" else None
        violations, row_idx = _aggregate_violations(col_idx, report, df, col)
        for v in violations:
            input_violation_ids.add(v["id"])
        violation_row_indices.update(row_idx)
        columns_payload.append({
            "name": col,
            "description": p.description,
            "dtype": p.dtype,
            "canonical_hint": p.canonical_hint,
            "format_spec": compact_format_summary(spec.format) if spec else None,
            "is_nullable": spec.is_nullable if spec else True,
            "target_casing": p.target_casing.value,
            "violations": violations,
            "value_corrections": _summarize_corrections(value_corrections.get(col, {})),
        })

    evidence_rows = _select_rows(df, group, sorted(violation_row_indices)[:_MAX_EVIDENCE_ROWS])
    clean_rows = _select_clean_rows(df, group, violation_row_indices)

    return (
        {
            "group_id": group_id,
            "columns": columns_payload,
            "evidence_rows": evidence_rows,
            "clean_reference_rows": clean_rows,
        },
        input_violation_ids,
    )


def _aggregate_violations(
    col_idx: int, report: ValidationReport | None, df: pd.DataFrame, col: str
) -> tuple[list[dict], list[int]]:
    if report is None or not report.violations:
        return [], []
    by_pattern: dict[str, list] = defaultdict(list)
    row_indices: list[int] = []
    for v in report.violations:
        by_pattern[v.expected_pattern or "unspecified"].append(v)
        if v.row_index >= 0:
            row_indices.append(v.row_index)
    if "not nullable" in by_pattern and col in df.columns:
        nan_idx = df.index[df[col].isna()].tolist()
        row_indices.extend(int(i) for i in nan_idx)

    aggregated: list[dict] = []
    for pat_idx, (pattern, items) in enumerate(by_pattern.items()):
        first = items[0]
        examples = list({str(it.value) for it in items if it.row_index >= 0})[:_EXAMPLES_PER_VIOLATION]
        aggregated.append({
            "id": f"c{col_idx}_v{pat_idx + 1}",
            "type": _classify_violation(pattern),
            "expected_pattern": pattern,
            "count": int(first.value) if pattern == "not nullable" else len(items),
            "examples": examples,
        })
    return aggregated, row_indices


def _classify_violation(pattern: str) -> str:
    if pattern == "not nullable":
        return "not_nullable"
    if pattern.startswith("^") or pattern.endswith("$"):
        return "regex_violation"
    return "format_violation"


def _select_rows(df: pd.DataFrame, group: list[str], indices: list[int]) -> list[dict]:
    valid = [i for i in indices if i in df.index]
    if not valid:
        return []
    cols = [c for c in group if c in df.columns]
    sub = df.loc[valid, cols].head(_MAX_EVIDENCE_ROWS)
    return [{"_row_id": int(i), **{c: _jsonable(row[c]) for c in cols}} for i, row in sub.iterrows()]


def _select_clean_rows(df: pd.DataFrame, group: list[str], dirty_indices: set[int]) -> list[dict]:
    cols = [c for c in group if c in df.columns]
    if not cols:
        return []
    clean_mask = df[cols].notna().all(axis=1) & ~df.index.isin(list(dirty_indices))
    sub = df.loc[clean_mask, cols].head(_MAX_CLEAN_ROWS)
    return [{"_row_id": int(i), **{c: _jsonable(row[c]) for c in cols}} for i, row in sub.iterrows()]


def _jsonable(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _invoke_with_retry(
    chain, system: str, ctx: dict, input_violation_ids: set[str], group: list[str]
) -> FixGroupResponse | None:
    for attempt in range(2):
        result: FixGroupResponse = chain.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)},
        ])
        errors = _coverage_errors(result, input_violation_ids, group)
        if not errors:
            return result
        if attempt == 0:
            ctx = {**ctx, "previous_response_was_invalid_because": errors}
    return result


def _coverage_errors(
    response: FixGroupResponse, input_violation_ids: set[str], group: list[str]
) -> list[str]:
    errors: list[str] = []
    addressed: set[str] = set()
    proposal_ids: set[str] = set()
    for p in response.proposals:
        proposal_ids.add(p.id)
        for vid in p.addresses_violations:
            if vid not in input_violation_ids:
                errors.append(f"proposal {p.id} addresses unknown violation id {vid}")
            addressed.add(vid)
        for col in p.affected_columns:
            if col not in group:
                errors.append(f"proposal {p.id} affects column {col} outside the group {group}")
    for p in response.proposals:
        for dep in p.depends_on:
            if dep not in proposal_ids:
                errors.append(f"proposal {p.id} depends on unknown proposal {dep}")
    declared = addressed | set(response.unaddressed_violation_ids)
    missing = input_violation_ids - declared
    if missing:
        errors.append(f"violations {sorted(missing)} are neither addressed nor declared unaddressed")
    return errors


def _namespace_proposal(group_id: str, proposal: FixProposal) -> FixProposal:
    return proposal.model_copy(update={
        "id": f"{group_id}_{proposal.id}",
        "depends_on": [f"{group_id}_{d}" for d in proposal.depends_on],
    })


def _empty_report(col: str) -> ValidationReport:
    return ValidationReport(column_name=col, violations=[])


def _summarize_corrections(corrections: dict[str, str | None]) -> dict:
    if not corrections:
        return {"examples": {}, "total_correctable": 0, "total_unaddressable": 0}
    correctable = {k: v for k, v in corrections.items() if v is not None}
    examples = dict(list(correctable.items())[:_CORRECTION_EXAMPLES])
    return {
        "examples": examples,
        "total_correctable": len(correctable),
        "total_unaddressable": len(corrections) - len(correctable),
    }
