"""Proposal Unified remediation agent: groups columns by related_columns transitive closure, aggregates upstream validation_reports into IDed violations per column, builds a per-group LLM payload (columns + evidence rows + clean reference rows), invokes structured FixGroupResponse output, runs coverage checks with one retry, then dry-runs each proposal in a sandbox and asks the same model to self-review the trial outcome — approving the proposal or regenerating with feedback — before writing group-prefixed proposals to state.proposed_fixes. The downstream Apply step still owns the real execution against state.dataset."""
from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd
from langchain_openai import ChatOpenAI

from models import (
    ColumnPayload,
    FixGroupResponse,
    FixProposal,
    FixReviewResponse,
    FormatSpec,
    ImputationHint,
    ValidationReport,
)
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.match_canonical import compact_format_summary
from tools.trial_execute import trial_execute
from utils.prompts import load_prompt


_MAX_EVIDENCE_ROWS = 10
_MAX_CLEAN_ROWS = 5
_EXAMPLES_PER_VIOLATION = 3
_CORRECTION_EXAMPLES = 20
_MAX_REVIEW_ITERATIONS = 2


def unified_node(state: PipelineState) -> PipelineState:
    if state.dataset is None or not state.payload:
        return state

    payload_by_name = {p.column_name: p for p in state.payload}
    reports_by_name = {r.column_name: r for r in state.validation_reports}
    specs_by_col = _specs_by_col(state.inferred_format_specs)
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
            specs_by_col=specs_by_col,
            imputation_hints=state.imputation_hints,
        ))

    deduped = dedupe_proposals(all_proposals)
    return state.model_copy(update={"proposed_fixes": deduped, "fix_groups": fix_groups})


def dedupe_proposals(proposals: list[FixProposal]) -> list[FixProposal]:
    seen: dict[tuple, FixProposal] = {}
    order: list[tuple] = []
    for p in proposals:
        key = _fingerprint(p)
        if key in seen:
            kept = seen[key]
            merged_addresses = list(dict.fromkeys(kept.addresses_violations + p.addresses_violations))
            merged_deps = list(dict.fromkeys(kept.depends_on + p.depends_on))
            seen[key] = kept.model_copy(update={
                "addresses_violations": merged_addresses,
                "depends_on": merged_deps,
            })
        else:
            seen[key] = p
            order.append(key)
    return [seen[k] for k in order]


def _fingerprint(p: FixProposal) -> tuple:
    return (
        frozenset(p.affected_columns),
        frozenset(p.addresses_violations),
        _normalize_code(p.code),
    )


def _normalize_code(code: str) -> str:
    return "\n".join(line.strip() for line in code.splitlines() if line.strip())


def propose_for_group(
    group_id: str,
    group: list[str],
    payload_by_name: dict[str, ColumnPayload],
    reports_by_name: dict[str, ValidationReport],
    df: pd.DataFrame,
    baseline,
    value_corrections: dict[str, dict[str, str | None]] | None = None,
    feedback: str = "",
    specs_by_col: dict[str, FormatSpec | None] | None = None,
    imputation_hints: dict[str, ImputationHint] | None = None,
) -> list[FixProposal]:
    chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0).with_structured_output(FixGroupResponse)
    system = load_prompt("unified")
    ctx, input_violation_ids = _build_group_context(
        group_id, group, payload_by_name, reports_by_name, df, baseline,
        value_corrections or {}, imputation_hints or {},
    )
    if feedback:
        ctx["user_feedback_on_previous_response"] = feedback
    response = _invoke_with_retry(chain, system, ctx, input_violation_ids, group)
    if response is None:
        return []

    reviewed = _review_and_revise_proposals(
        proposals=response.proposals,
        group=group,
        df=df,
        value_corrections=value_corrections or {},
        specs_by_col=specs_by_col or {},
        reports_by_name=reports_by_name,
        imputation_hints=imputation_hints or {},
        regenerate=lambda fb: _regenerate_proposal(
            chain, system, ctx, input_violation_ids, group, fb,
        ),
    )
    return [_namespace_proposal(group_id, p) for p in reviewed]


def _review_and_revise_proposals(
    proposals: list[FixProposal],
    group: list[str],
    df: pd.DataFrame,
    value_corrections: dict[str, dict[str, str | None]],
    specs_by_col: dict[str, FormatSpec | None],
    reports_by_name: dict[str, ValidationReport],
    imputation_hints: dict[str, ImputationHint],
    regenerate,
) -> list[FixProposal]:
    review_chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0).with_structured_output(FixReviewResponse)
    review_system = load_prompt("unified_review")
    finalized: list[FixProposal] = []
    for proposal in proposals:
        current = proposal
        for _ in range(_MAX_REVIEW_ITERATIONS):
            trial = trial_execute(
                df, current, value_corrections, specs_by_col, reports_by_name,
                imputation_hints=imputation_hints,
            )
            breaches = trial.get("invariant_violations") or []
            if breaches:
                replacement = regenerate(_invariant_feedback_for(current, breaches))
                if replacement is None:
                    current = None
                    break
                current = replacement.model_copy(update={
                    "id": proposal.id,
                    "depends_on": proposal.depends_on,
                })
                continue
            review_ctx = {
                "proposal": current.model_dump(),
                "trial": trial,
                "context": {
                    "group_columns": group,
                    "addresses_violations_count": len(current.addresses_violations),
                },
            }
            review: FixReviewResponse = review_chain.invoke([
                {"role": "system", "content": review_system},
                {"role": "user", "content": json.dumps(review_ctx, ensure_ascii=False, default=str)},
            ])
            if review.decision == "approve":
                break
            replacement = regenerate(_review_feedback_for(current, trial, review.feedback))
            if replacement is None:
                break
            current = replacement.model_copy(update={
                "id": proposal.id,
                "depends_on": proposal.depends_on,
            })
        if current is not None and not _breaks_invariants(
            current, df, value_corrections, specs_by_col, reports_by_name, imputation_hints
        ):
            finalized.append(current)
    return finalized


def _breaks_invariants(
    proposal: FixProposal,
    df: pd.DataFrame,
    value_corrections: dict[str, dict[str, str | None]],
    specs_by_col: dict[str, FormatSpec | None],
    reports_by_name: dict[str, ValidationReport],
    imputation_hints: dict[str, ImputationHint],
) -> bool:
    trial = trial_execute(
        df, proposal, value_corrections, specs_by_col, reports_by_name,
        imputation_hints=imputation_hints,
    )
    return bool(trial.get("invariant_violations"))


def _invariant_feedback_for(proposal: FixProposal, breaches: list[str]) -> str:
    return (
        f"Proposal {proposal.id} was rejected: it breaks non-negotiable invariants. "
        + " ".join(breaches)
        + " Rewrite it so that no missing value is filled without an imputation hint, "
        "no column ends up holding values that differ only by casing, and the row count "
        "is preserved unless the fix is an explicit deduplication."
    )


def _regenerate_proposal(
    chain, system: str, ctx: dict, input_violation_ids: set[str], group: list[str], feedback: str,
) -> FixProposal | None:
    revised_ctx = {**ctx, "user_feedback_on_previous_response": feedback}
    response = _invoke_with_retry(chain, system, revised_ctx, input_violation_ids, group)
    if response is None or not response.proposals:
        return None
    return response.proposals[0]


def _review_feedback_for(proposal: FixProposal, trial: dict, reviewer_feedback: str) -> str:
    parts = [f"Proposal {proposal.id} was rejected by self-review."]
    if reviewer_feedback:
        parts.append(f"Reviewer note: {reviewer_feedback}")
    if trial.get("status") == "error":
        parts.append(f"Trial raised: {trial.get('error', '')}")
    else:
        parts.append(
            f"Trial changed {trial.get('rows_changed', 0)} rows; "
            f"violation_delta={trial.get('violation_delta', {})}"
        )
    return " ".join(parts)


def _specs_by_col(inferred: dict[str, dict]) -> dict[str, FormatSpec | None]:
    from models import DateFormat, EnumFormat, RangeFormat, RegexFormat
    out: dict[str, FormatSpec | None] = {}
    for col, info in inferred.items():
        spec = info.get("final_spec")
        if not spec:
            out[col] = None
            continue
        kind = spec.get("type")
        if kind == "regex":
            out[col] = RegexFormat(**spec)
        elif kind == "enum":
            out[col] = EnumFormat(**spec)
        elif kind == "range":
            out[col] = RangeFormat(**spec)
        elif kind == "date":
            out[col] = DateFormat(**spec)
        else:
            out[col] = None
    return out


def _build_groups(payload: list[ColumnPayload]) -> list[list[str]]:
    parent: dict[str, str] = {p.column_name: p.column_name for p in payload}
    names = list(parent.keys())

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

    description_links = _description_mentions(payload, names)
    for a, b in description_links:
        union(a, b)

    hint_stem_links = _canonical_hint_stems(payload)
    for a, b in hint_stem_links:
        union(a, b)

    grouped: dict[str, list[str]] = defaultdict(list)
    for p in payload:
        grouped[find(p.column_name)].append(p.column_name)
    return list(grouped.values())


def _description_mentions(payload: list[ColumnPayload], names: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    name_set = {n.lower() for n in names}
    for p in payload:
        desc = (p.description or "").lower()
        if not desc:
            continue
        for other in names:
            if other == p.column_name:
                continue
            token = other.lower()
            if len(token) < 3:
                continue
            if token in desc and token in name_set:
                pairs.append((p.column_name, other))
    return pairs


def _canonical_hint_stems(payload: list[ColumnPayload]) -> list[tuple[str, str]]:
    by_stem: dict[str, list[str]] = defaultdict(list)
    for p in payload:
        if not p.canonical_hint or p.canonical_hint == "NaN":
            continue
        stem = _strip_axis_suffix(p.canonical_hint)
        if stem != p.canonical_hint:
            by_stem[stem].append(p.column_name)
    pairs: list[tuple[str, str]] = []
    for cols in by_stem.values():
        if len(cols) < 2:
            continue
        anchor = cols[0]
        for other in cols[1:]:
            pairs.append((anchor, other))
    return pairs


_AXIS_SUFFIXES = ("_min", "_max", "_inizio", "_fine", "_start", "_end", "_da", "_a", "_from", "_to")


def _strip_axis_suffix(hint: str) -> str:
    lower = hint.lower()
    for suf in _AXIS_SUFFIXES:
        if lower.endswith(suf):
            return lower[: -len(suf)]
    return lower


def _build_group_context(
    group_id: str,
    group: list[str],
    payload_by_name: dict[str, ColumnPayload],
    reports_by_name: dict[str, ValidationReport],
    df: pd.DataFrame,
    baseline,
    value_corrections: dict[str, dict[str, str | None]],
    imputation_hints: dict[str, ImputationHint],
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
            "related_columns": [r for r in p.related_columns if r in df.columns],
            "violations": violations,
            "value_corrections": _summarize_corrections(value_corrections.get(col, {})),
            "imputation_hint": _summarize_hint(imputation_hints.get(col)),
        })

    evidence_rows = _select_rows(df, group, sorted(violation_row_indices)[:_MAX_EVIDENCE_ROWS])
    clean_rows = _select_clean_rows(df, group, violation_row_indices)
    context_columns = _context_columns(group, payload_by_name, df)

    return (
        {
            "group_id": group_id,
            "columns": columns_payload,
            "evidence_rows": evidence_rows,
            "clean_reference_rows": clean_rows,
            "context_columns": context_columns,
        },
        input_violation_ids,
    )


def _context_columns(
    group: list[str], payload_by_name: dict[str, ColumnPayload], df: pd.DataFrame
) -> list[dict]:
    in_group = set(group)
    neighbors: list[str] = []
    seen: set[str] = set()
    for col in group:
        p = payload_by_name.get(col)
        if p is None:
            continue
        for r in p.related_columns:
            if r in in_group or r in seen or r not in df.columns:
                continue
            seen.add(r)
            neighbors.append(r)
    out: list[dict] = []
    for col in neighbors:
        p = payload_by_name.get(col)
        if p is None:
            continue
        out.append({
            "name": col,
            "description": p.description,
            "dtype": p.dtype,
            "sample": [_jsonable(v) for v in df[col].dropna().head(5).tolist()],
        })
    return out


def _aggregate_violations(
    col_idx: int, report: ValidationReport | None, df: pd.DataFrame, col: str
) -> tuple[list[dict], list[int]]:
    if report is None or not report.violations:
        return [], []
    by_pattern: dict[str, list] = defaultdict(list)
    row_indices: list[int] = []
    for v in report.violations:
        if str(v.expected_pattern or "").startswith(_SCHEMA_ONLY_PREFIX):
            continue
        by_pattern[v.expected_pattern or "unspecified"].append(v)
        if v.row_index >= 0:
            row_indices.append(v.row_index)
    if any(p in by_pattern for p in _MISSING_PATTERNS) and col in df.columns:
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
            "count": int(first.value) if pattern in _MISSING_PATTERNS else len(items),
            "examples": examples,
        })
    return aggregated, row_indices


_MISSING_PATTERNS = {"not nullable", "missing value"}
_SCHEMA_ONLY_PREFIX = "naming convention"


def _classify_violation(pattern: str) -> str:
    if pattern == "not nullable":
        return "not_nullable"
    if pattern == "missing value":
        return "missing_value"
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


_HINT_EXAMPLES = 10


def _summarize_hint(hint: ImputationHint | None) -> dict | None:
    if hint is None:
        return None
    examples = dict(list(hint.mapping.items())[:_HINT_EXAMPLES])
    return {
        "predictor_columns": hint.predictor_columns,
        "path": hint.path,
        "purity": round(hint.purity, 4),
        "coverage": round(hint.coverage, 4),
        "confidence": hint.confidence,
        "mapping_size": len(hint.mapping),
        "mapping_examples": examples,
        "rationale": hint.rationale,
    }


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
