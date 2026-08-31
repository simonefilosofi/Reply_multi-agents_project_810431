"""Unified Remediation agent. Groups columns by the transitive closure of related_columns, aggregates upstream validation reports into identified violations, and asks the model for proposals per group: typed catalogue operations for anything structural, generated cleaning functions for value-level repair, so a format rule generalises rather than enumerating the values already seen. Every generated function is cleared by a static gate and executed against its own column's evidence before the proposal is dry-run; a failure becomes deterministic feedback and another attempt, and a failure that repeats identically escalates once to a critic that diagnoses without writing code. What survives is dry-run, self-reviewed and written to state.proposed_fixes; the Apply step owns execution against the dataset. A group the model cannot answer at all - a reply cut off at the output limit, or one no decoding path parses - costs that group and no more: it is recorded on state.errors as unaddressed and the run continues, so the remaining groups, the schema proposals and the report still reach the user."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import NamedTuple

import pandas as pd

from models import (
    CleanerDiagnosis,
    CleanerIssue,
    ColumnPayload,
    FixGroupResponse,
    UnaddressedViolations,
    FixProposal,
    FixReviewResponse,
    FormatSpec,
    ImputationHint,
    ValidationReport,
)
from state import PipelineState
from tools.baseline_accessors import find_spec_by_hint
from tools.match_canonical import compact_format_summary
from tools.operations import describe_operation
from tools.schema_proposals import schema_proposals
from tools.fix_invariants import removable_values
from tools.generated_function import (
    close_sandbox,
    execution_issues,
    execution_log,
    issues_fingerprint,
    start_execution_log,
    validate_against_examples,
)
from tools.trial_execute import trial_execute
from tools.validate_format import specs_by_column
from utils.llm import EmptyModelResponse, structured_model
from utils.prompts import load_prompt


_MAX_EVIDENCE_ROWS = 10
_MAX_CLEAN_ROWS = 5
_EXAMPLES_PER_VIOLATION = 3
_MAX_PATTERNS_PER_COLUMN = 25
_CORRECTION_EXAMPLES = 20
_MAX_EXAMPLE_VALUES = 8
_MAX_REVIEW_ITERATIONS = 3
_MAX_REPORTED_ISSUES = 5


class GroupOutcome(NamedTuple):
    """Both halves of a group's answer: what the model proposed, and what it could not fix."""
    proposals: list[FixProposal]
    unaddressed: list[UnaddressedViolations]


def declared_unaddressed(
    group_id: str, columns: list[str], response: FixGroupResponse, affected_rows: int = 0,
    by_column: dict[str, int] | None = None,
) -> UnaddressedViolations | None:
    """The model's own statement of what it cannot fix. The prompt requires it and _coverage_errors
    refuses a response that omits one, so this is an answer already being produced and validated.
    The columns recorded are the ones still carrying a violation, not the whole group, because a
    group is a unit of reasoning and naming all of it would blame columns that came out clean."""
    if not response.unaddressed_violation_ids:
        return None
    return UnaddressedViolations(
        group_id=group_id,
        columns=list(columns),
        violation_ids=list(response.unaddressed_violation_ids),
        reason=response.rationale_for_unaddressed,
        affected_rows=affected_rows,
        affected_by_column=dict(by_column or {}),
        source="model",
    )


def unexplained_columns(
    group: list[str], reports_by_name: dict, proposals: list[FixProposal]
) -> list[str]:
    """Columns of the group that still carry a violation no proposal touches. Schema proposals
    count here as much as the model's: a column with a rename waiting at the gate has an action,
    and listing it as unactionable would be wrong."""
    proposed = {column for p in proposals for column in p.affected_columns}
    return [
        column for column in group
        if column not in proposed
        and reports_by_name.get(column) and reports_by_name[column].violations
    ]


def violation_rows(columns: list[str], reports_by_name: dict) -> int:
    return sum(rows_by_column(columns, reports_by_name).values())


def rows_by_column(columns: list[str], reports_by_name: dict) -> dict[str, int]:
    """Rows affected per column. Reported per column rather than as a total, because the totals
    are per-column counts that overlap: summing them over a group states more affected rows than
    the file has, which reads as nonsense next to the row count."""
    return {
        column: sum(v.affected_rows or 1 for v in reports_by_name[column].violations)
        for column in columns if reports_by_name.get(column)
    }


def unaddressed_backstop(
    group_id: str,
    group: list[str],
    reports_by_name: dict,
    proposals: list[FixProposal],
    declared: list[UnaddressedViolations],
    imputation_hints: dict,
    reason: str = "",
) -> UnaddressedViolations | None:
    """What the group still leaves unexplained once the proposals and the model's declaration are
    both accounted for. _invoke_with_retry returns the second attempt even when coverage errors
    remain, so a violation can reach the report having been neither fixed nor declared."""
    covered = {vid for p in proposals for vid in p.addresses_violations}
    covered |= {vid for entry in declared for vid in entry.violation_ids}
    outstanding = [
        column for column in unexplained_columns(group, reports_by_name, proposals)
        if not any(column in entry.columns for entry in declared)
    ]
    if not outstanding:
        return None
    by_column = rows_by_column(outstanding, reports_by_name)
    return UnaddressedViolations(
        group_id=group_id,
        columns=outstanding,
        violation_ids=sorted({f"{column}:unaddressed" for column in outstanding} - covered),
        reason=reason or _no_action_reason(outstanding, imputation_hints),
        affected_rows=sum(by_column.values()),
        affected_by_column=by_column,
        source="pipeline",
    )


def _no_action_reason(columns: list[str], imputation_hints: dict) -> str:
    without_predictor = [c for c in columns if c not in imputation_hints]
    if without_predictor:
        return (
            f"no column in the dataset determines {', '.join(without_predictor)}, so the gap "
            "cannot be filled without inventing a value"
        )
    return "no corrective action could be expressed as code over the existing columns"


def without_columns_already_actioned(
    carried: list[UnaddressedViolations], proposals: list[FixProposal]
) -> list[UnaddressedViolations]:
    """Drops from each carried entry the columns some proposal does cover, and drops an entry left
    with none. A group is answered before the schema proposals are built, so a column whose only
    fault is its name can be declared unactionable and then be renamed at the gate anyway."""
    proposed = {column for p in proposals for column in p.affected_columns}
    kept: list[UnaddressedViolations] = []
    for entry in carried:
        remaining = [column for column in entry.columns if column not in proposed]
        if not remaining:
            continue
        if remaining == entry.columns:
            kept.append(entry)
            continue
        elsewhere = [column for column in entry.columns if column in proposed]
        kept.append(entry.model_copy(update={
            "columns": remaining,
            "actioned_elsewhere": elsewhere,
            "affected_by_column": {c: n for c, n in entry.affected_by_column.items()
                                   if c in remaining},
            "affected_rows": sum(n for c, n in entry.affected_by_column.items()
                                 if c in remaining) or entry.affected_rows,
        }))
    return kept


def unified_node(state: PipelineState) -> PipelineState:
    if state.dataset is None or not state.payload:
        return state

    start_execution_log()
    payload_by_name = {p.column_name: p for p in state.payload}
    reports_by_name = {r.column_name: r for r in state.validation_reports}
    specs_by_col = _specs_by_col(state.inferred_format_specs)
    groups = _build_groups(state.payload)

    actionable = [g for g in groups if any(reports_by_name.get(c, _empty_report(c)).violations for c in g)]
    if not actionable:
        return state.model_copy(update={
            "proposed_fixes": [
                _with_readable_code(p)
                for p in schema_proposals(state.validation_reports, list(state.dataset.columns))
            ],
            "fix_groups": {},
        })

    anomalies_by_column = {
        r.column_name: {
            "method": r.method,
            "detected": int(r.stats.get("detected", len(r.anomalies))),
            "comment": r.comment,
            "examples": [a.value for a in r.anomalies[:5]],
        }
        for r in state.anomaly_reports
    }
    schema = schema_proposals(state.validation_reports, list(state.dataset.columns))
    all_proposals: list[FixProposal] = []
    fix_groups: dict[str, list[str]] = {}
    failures: list[str] = []
    unaddressed: list[UnaddressedViolations] = []
    for group_idx, group in enumerate(actionable):
        group_id = f"g{group_idx + 1}"
        fix_groups[group_id] = group
        group_proposals: list[FixProposal] = []
        group_declared: list[UnaddressedViolations] = []
        group_reason = ""
        try:
            outcome = propose_for_group(
                group_id, group, payload_by_name, reports_by_name, state.dataset, state.baseline,
                value_corrections=state.value_corrections,
                specs_by_col=specs_by_col,
                imputation_hints=state.imputation_hints,
                removable_by_column=removable_values(state.payload, state.validation_reports),
                anomalies=anomalies_by_column,
            )
            group_proposals = outcome.proposals
            group_declared = outcome.unaddressed
            all_proposals.extend(group_proposals)
            unaddressed.extend(group_declared)
        except EmptyModelResponse as error:
            failures.append(
                f"{group_id} ({', '.join(group)}): no proposals, the model returned no usable "
                f"answer ({error}). The violations in this group are reported but unaddressed."
            )
            group_reason = (
                "the model returned no usable answer for this group, so no corrective action "
                "was produced for the violations in it"
            )
        remainder = unaddressed_backstop(
            group_id, group, reports_by_name, group_proposals + schema, group_declared,
            state.imputation_hints, group_reason,
        )
        if remainder is not None:
            unaddressed.append(remainder)

    deduped = _drop_redundant_schema_fixes(dedupe_proposals(all_proposals), schema)
    runs = execution_log()
    close_sandbox()
    return state.model_copy(update={
        "proposed_fixes": [_with_readable_code(p) for p in schema + deduped],
        "fix_groups": fix_groups,
        "generated_function_runs": runs,
        "errors": state.errors + failures,
        "unaddressed_violations": state.unaddressed_violations + without_columns_already_actioned(
            unaddressed, schema + deduped
        ),
    })


def _with_readable_code(proposal: FixProposal) -> FixProposal:
    if proposal.code or not proposal.operations:
        return proposal
    return proposal.model_copy(update={
        "code": "\n".join(describe_operation(o) for o in proposal.operations)
    })


def _drop_redundant_schema_fixes(
    proposals: list[FixProposal], schema: list[FixProposal]
) -> list[FixProposal]:
    covered = {
        (operation.kind, operation.column)
        for proposal in schema
        for operation in proposal.operations
    }
    return [
        proposal for proposal in proposals
        if not any((o.kind, o.column) in covered for o in proposal.operations)
    ]


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
    return _drop_subsumed([seen[k] for k in order])


def _drop_subsumed(proposals: list[FixProposal]) -> list[FixProposal]:
    ranked = sorted(proposals, key=lambda p: -len(p.addresses_violations))
    kept: list[FixProposal] = []
    for proposal in ranked:
        covered = set(proposal.addresses_violations)
        columns = set(proposal.affected_columns)
        if covered and any(
            columns == set(other.affected_columns) and covered <= set(other.addresses_violations)
            for other in kept
        ):
            continue
        kept.append(proposal)
    return [p for p in proposals if p in kept]


def _fingerprint(p: FixProposal) -> tuple:
    return (frozenset(p.affected_columns), frozenset(p.addresses_violations))


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
    removable_by_column: dict[str, set] | None = None,
    anomalies: dict[str, dict] | None = None,
) -> GroupOutcome:
    chain = structured_model(FixGroupResponse)
    system = load_prompt("unified")
    ctx, input_violation_ids = _build_group_context(
        group_id, group, payload_by_name, reports_by_name, df, baseline,
        value_corrections or {}, imputation_hints or {},
    )
    detected_anomalies = {c: a for c, a in (anomalies or {}).items() if c in group}
    if detected_anomalies:
        ctx["detected_anomalies"] = detected_anomalies
    if feedback:
        ctx["user_feedback_on_previous_response"] = feedback
    response = _invoke_with_retry(chain, system, ctx, input_violation_ids, group)
    if response is None:
        return GroupOutcome(proposals=[], unaddressed=[])

    reviewed = _review_and_revise_proposals(
        proposals=_drop_unusable_proposals(response.proposals, group),
        group=group,
        examples_by_column=_examples_by_column(ctx),
        df=df,
        removable_by_column=removable_by_column or {},
        value_corrections=value_corrections or {},
        specs_by_col=specs_by_col or {},
        reports_by_name=reports_by_name,
        imputation_hints=imputation_hints or {},
        regenerate=lambda fb: _regenerate_proposal(
            chain, system, ctx, input_violation_ids, group, fb,
        ),
    )
    namespaced = [_namespace_proposal(group_id, p) for p in reviewed]
    still_open = unexplained_columns(group, reports_by_name, namespaced)
    open_by_column = rows_by_column(still_open, reports_by_name)
    declared = declared_unaddressed(
        group_id, still_open, response, sum(open_by_column.values()), open_by_column
    )
    return GroupOutcome(
        proposals=namespaced,
        unaddressed=[declared] if declared is not None and still_open else [],
    )


def _review_and_revise_proposals(
    proposals: list[FixProposal],
    group: list[str],
    examples_by_column: dict[str, dict],
    df: pd.DataFrame,
    removable_by_column: dict[str, set],
    value_corrections: dict[str, dict[str, str | None]],
    specs_by_col: dict[str, FormatSpec | None],
    reports_by_name: dict[str, ValidationReport],
    imputation_hints: dict[str, ImputationHint],
    regenerate,
) -> list[FixProposal]:
    review_chain = structured_model(FixReviewResponse)
    review_system = load_prompt("unified_review")
    finalized: list[FixProposal] = []
    for proposal in proposals:
        current = proposal
        previous_fingerprint: tuple[str, ...] = ()
        critic_spent = False
        for _ in range(_MAX_REVIEW_ITERATIONS):
            cleaner_issues = _validate_generated_operations(current, examples_by_column, df)
            if cleaner_issues:
                repeated = issues_fingerprint(cleaner_issues) == previous_fingerprint
                previous_fingerprint = issues_fingerprint(cleaner_issues)
                if repeated and not critic_spent:
                    critic_spent = True
                    feedback = _critic_feedback_for(current, cleaner_issues, examples_by_column)
                else:
                    feedback = _cleaner_feedback_for(current, cleaner_issues)
                replacement = regenerate(feedback)
                if replacement is None:
                    current = None
                    break
                current = replacement.model_copy(update={
                    "id": proposal.id,
                    "depends_on": proposal.depends_on,
                })
                continue
            trial = trial_execute(
                df, current, value_corrections, specs_by_col, reports_by_name,
                imputation_hints=imputation_hints,
                removable_by_column=removable_by_column,
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
        if current is None or _validate_generated_operations(current, examples_by_column, df):
            continue
        if not _breaks_invariants(
            current, df, value_corrections, specs_by_col, reports_by_name, imputation_hints,
            removable_by_column,
        ):
            finalized.append(current)
    return finalized


def _validate_generated_operations(
    proposal: FixProposal, examples_by_column: dict[str, dict], df: pd.DataFrame | None = None
) -> list[CleanerIssue]:
    """Clears every generated function a proposal carries against its own column's evidence,
    before the proposal is dry-run and before a human ever sees it. The static gate runs first
    and short-circuits, so malformed or forbidden source never reaches an interpreter.

    A column with no collected examples used to leave the value list empty, and a cleaner that
    runs zero times returns no issues: the function cleared the gate having never executed and
    could still raise on the real column. Evidence therefore falls back to the column itself, and
    a function with nothing at all to run against is refused rather than assumed sound."""
    issues: list[CleanerIssue] = []
    for operation in proposal.operations:
        if operation.kind != "apply_generated_function":
            continue
        examples = examples_by_column.get(operation.column, {})
        dominant = list(examples.get("dominant", []))
        inconsistent = list(examples.get("inconsistent", []))
        dtype = examples.get("dtype", "")
        if not dominant and not inconsistent:
            sampled, _ = _sampled_evidence(df, operation.column)
            if sampled:
                issues.extend(execution_issues(operation.source, sampled))
                continue
            issues.append(CleanerIssue(
                category="not_validated",
                message=(
                    f"no values were available to run the cleaner for {operation.column!r} "
                    "against, so it cannot be shown to work."
                ),
                expected_behavior="be executable against at least one value of its own column.",
            ))
            continue
        found, _ = validate_against_examples(operation.source, dominant, inconsistent, dtype)
        issues.extend(found)
    return issues


def _sampled_evidence(df: pd.DataFrame | None, column: str) -> tuple[list, str]:
    """Values taken straight from the column, as the fallback when none were collected. They are
    read in the column's own rendering, which is what the cleaner will actually be handed."""
    if df is None or column not in df.columns:
        return [], ""
    populated = df[column].dropna()
    if populated.empty:
        return [], ""
    return _distinct_head(populated), str(df[column].dtype)


def _examples_by_column(ctx: dict) -> dict[str, dict]:
    return {
        column["name"]: {
            "dominant": column.get("dominant_example_values", []),
            "inconsistent": column.get("example_inconsistent_values", []),
            "dtype": column.get("dtype", ""),
        }
        for column in ctx.get("columns", [])
    }


def _drop_unusable_proposals(proposals: list[FixProposal], group: list[str]) -> list[FixProposal]:
    """Discards what the model returned but cannot be executed: a proposal with no operations, one
    naming a column outside the group, or one depending on a proposal that is not there. Namespacing
    rebuilds affected_columns from the operations, so an invented column name would otherwise
    survive the coverage check and reach the gate; and a dangling dependency survived it too,
    because the retry that refuses one still returns its second attempt, leaving a proposal to be
    approved by a reviewer and then refused by apply_fixes for the dependency it never had."""
    in_group = set(group)
    usable: list[FixProposal] = []
    for proposal in proposals:
        if not proposal.operations:
            continue
        targets = {operation.column for operation in proposal.operations if operation.column}
        if targets - in_group:
            continue
        usable.append(proposal)
    return _without_dangling_dependencies(usable)


def _without_dangling_dependencies(proposals: list[FixProposal]) -> list[FixProposal]:
    """Drops proposals whose dependencies are absent, repeatedly, since dropping one can strand
    another that depended on it."""
    kept = list(proposals)
    while True:
        present = {proposal.id for proposal in kept}
        remaining = [p for p in kept if not (set(p.depends_on) - present)]
        if len(remaining) == len(kept):
            return remaining
        kept = remaining


def _cleaner_feedback_for(proposal: FixProposal, issues: list[CleanerIssue]) -> str:
    lines = [
        f"The cleaning function in proposal {proposal.id} failed validation against the column's "
        f"own values. Rewrite it so that every point below is resolved."
    ]
    for issue in issues[:_MAX_REPORTED_ISSUES]:
        lines.append(
            f"- input {issue.input_value!r} produced {issue.actual_output!r}: "
            f"{issue.message} Expected behaviour: {issue.expected_behavior}"
        )
    return " ".join(lines)


def _critic_feedback_for(
    proposal: FixProposal, issues: list[CleanerIssue], examples_by_column: dict[str, dict]
) -> str:
    """Escalates a failure the deterministic feedback did not unblock. A second model reads the
    failed function and the findings and prescribes the repair; it never writes the code itself,
    so the generator stays the only author."""
    generated = next(
        (o for o in proposal.operations if o.kind == "apply_generated_function"), None
    )
    if generated is None:
        return _cleaner_feedback_for(proposal, issues)
    examples = examples_by_column.get(generated.column, {})
    chain = structured_model(CleanerDiagnosis)
    diagnosis: CleanerDiagnosis = chain.invoke([
        {"role": "system", "content": load_prompt("cleaner_critic")},
        {"role": "user", "content": json.dumps({
            "column": generated.column,
            "source": generated.source,
            "issues": [issue.model_dump() for issue in issues[:_MAX_REPORTED_ISSUES]],
            "dominant_example_values": examples.get("dominant", []),
            "example_inconsistent_values": examples.get("inconsistent", []),
        }, ensure_ascii=False, default=str)},
    ])
    repairs = " ".join(
        f"For {repair.input_value!r} produce {repair.expected_output!r}: {repair.fix_note}"
        for repair in diagnosis.exact_repairs[:_MAX_REPORTED_ISSUES]
    )
    return (
        f"The cleaning function in proposal {proposal.id} failed the same way twice, so the "
        f"previous feedback was not enough. Diagnosis: {diagnosis.root_cause} "
        f"The defect is in {diagnosis.bug_location}. Required fix: {diagnosis.planned_fix} "
        f"{repairs}"
    )


def _breaks_invariants(
    proposal: FixProposal,
    df: pd.DataFrame,
    value_corrections: dict[str, dict[str, str | None]],
    specs_by_col: dict[str, FormatSpec | None],
    reports_by_name: dict[str, ValidationReport],
    imputation_hints: dict[str, ImputationHint],
    removable_by_column: dict[str, set],
) -> bool:
    trial = trial_execute(
        df, proposal, value_corrections, specs_by_col, reports_by_name,
        imputation_hints=imputation_hints,
        removable_by_column=removable_by_column,
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
    return specs_by_column(inferred)


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
            **_format_examples(report, df[col] if col in df.columns else None),
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


def _format_examples(report: ValidationReport | None, series: pd.Series | None) -> dict:
    """Splits the column into the values that already conform and the values that do not, taken
    from the rows the format validator flagged. A generated cleaning function is judged against
    exactly these two lists: it must leave the first untouched and rewrite the second."""
    if series is None:
        return {"dominant_example_values": [], "example_inconsistent_values": []}
    offending_rows = {
        violation.row_index
        for violation in (report.violations if report else [])
        if violation.kind == "format" and violation.row_index >= 0
    }
    populated = series.dropna()
    offending = populated[populated.index.isin(offending_rows)]
    conforming = populated[~populated.index.isin(offending_rows)]
    return {
        "dominant_example_values": _distinct_head(conforming),
        "example_inconsistent_values": _distinct_head(offending),
    }


def _distinct_head(series: pd.Series) -> list:
    seen: list = []
    for value in series:
        rendered = _jsonable(value)
        if rendered not in seen:
            seen.append(rendered)
        if len(seen) == _MAX_EXAMPLE_VALUES:
            break
    return seen


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
        if v.kind in _SCHEMA_ONLY_KINDS:
            continue
        by_pattern[v.expected_pattern or "unspecified"].append(v)
        if v.row_index >= 0:
            row_indices.append(v.row_index)
    if any(p in by_pattern for p in _MISSING_PATTERNS) and col in df.columns:
        nan_idx = df.index[df[col].isna()].tolist()
        row_indices.extend(int(i) for i in nan_idx)

    ranked = sorted(by_pattern.items(), key=lambda entry: -len(entry[1]))
    aggregated: list[dict] = []
    for pat_idx, (pattern, items) in enumerate(ranked[:_MAX_PATTERNS_PER_COLUMN]):
        first = items[0]
        examples = list({str(it.value) for it in items if it.row_index >= 0})[:_EXAMPLES_PER_VIOLATION]
        aggregated.append({
            "id": f"c{col_idx}_v{pat_idx + 1}",
            "type": _prompt_label(first),
            "expected_pattern": pattern,
            "count": first.affected_rows if pattern in _MISSING_PATTERNS else len(items),
            "examples": examples,
        })
    aggregated += _remainder_entries(col_idx, ranked[_MAX_PATTERNS_PER_COLUMN:], len(aggregated))
    return aggregated, row_indices


def _remainder_entries(col_idx: int, tail: list, offset: int) -> list[dict]:
    """Folds the long tail of one-off patterns into one entry per violation kind. A cross-
    column pattern names the key that implies the value, so a column can carry as many
    patterns as it has keys; sending every one would bury the frequent, fixable cases."""
    by_kind: dict[str, list] = defaultdict(list)
    for pattern, items in tail:
        by_kind[_prompt_label(items[0])].extend(items)
    entries = []
    for index, (kind, items) in enumerate(sorted(by_kind.items())):
        examples = list({str(it.value) for it in items if it.row_index >= 0})[:_EXAMPLES_PER_VIOLATION]
        entries.append({
            "id": f"c{col_idx}_v{offset + index + 1}",
            "type": kind,
            "expected_pattern": f"{len(items)} further {kind} violations across scattered patterns",
            "count": len(items),
            "examples": examples,
        })
    return entries


_MISSING_PATTERNS = {"not nullable", "missing value"}
_SCHEMA_ONLY_KINDS = ("schema", "uniqueness")


def _prompt_label(violation) -> str:
    """The labels the prompt has always used, now derived from the typed kind rather than
    re-parsed out of the message text. prompts/unified.md is unchanged."""
    pattern = str(violation.expected_pattern or "")
    if pattern == "not nullable":
        return "not_nullable"
    if pattern == "missing value":
        return "missing_value"
    if violation.kind == "format" and (pattern.startswith("^") or pattern.endswith("$")):
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
    result: FixGroupResponse | None = None
    for attempt in range(2):
        try:
            result = chain.invoke([
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)},
            ])
        except EmptyModelResponse:
            return None
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
        "code": "\n".join(describe_operation(o) for o in proposal.operations),
        "affected_columns": sorted({
            getattr(o, "column", "") for o in proposal.operations if getattr(o, "column", "")
        }) or proposal.affected_columns,
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
