"""Detects exact and near-duplicate columns via pairwise similarity, keeps the member that agrees best with the rest of the table - measured, not assumed - fills its gaps from the siblings, and elects the canonical name for each group. Similarity is measured on the string form and again on the numeric form, so that columns differing only by zero-padding or storage type are still recognised as duplicates. Validation reports follow the columns: those of dropped members are discarded and the survivor's are renamed. The election is deterministic whenever exactly one group member already satisfies the baseline naming convention; the LLM is consulted only to break ties or when no member conforms, and its answer is normalised and validated before use."""
from __future__ import annotations

import json
from collections import defaultdict

import pandas as pd
from pydantic import BaseModel

from models import DuplicateResolution, FormatViolation, ValidationReport
from state import PipelineState
from tools.change_log import diff_values_only
from tools.cross_column_checks import coherence_score
from tools.validate_column_names import is_conforming, normalize_column_name, uniquify
from utils.llm import structured_model
from utils.prompts import load_prompt


_SIMILARITY_THRESHOLD = 0.80
_DIVERGENCE_ALERT_RATIO = 0.01
_MAX_LOST_VALUES = 10


class _NameElection(BaseModel):
    canonical_name: str
    rationale: str


def duplicate_column_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset
    groups = [g for g in _find_groups(list(df.columns), df) if len(g) > 1]
    if not groups:
        return state.model_copy(update={"surviving_columns": list(df.columns)})

    chain = structured_model(_NameElection)
    system = load_prompt("duplicate_column")
    baseline_columns = _baseline_columns_for_domain(state)

    conventions = state.baseline.global_conventions if state.baseline else None
    taken: set[str] = {c for c in df.columns}

    new_df = df.copy()
    divergence_reports: list[ValidationReport] = []
    dropped: set[str] = set()
    renames: dict[str, str] = {}
    resolutions: list[DuplicateResolution] = []

    for group in groups:
        data_survivor, selection = _elect_data_survivor(new_df, group)
        election = _elect_canonical_name(
            group, chain, system, state.detected_domain, baseline_columns, conventions, taken
        )
        taken.add(election.canonical_name)

        overwritten: dict[str, int] = {}
        lost: dict[str, list] = {}
        backfilled = 0
        for c in group:
            if c == data_survivor:
                continue
            overwritten[c], lost[c] = _divergence(new_df[data_survivor], new_df[c])
            mask = new_df[data_survivor].isna() & new_df[c].notna()
            if not mask.any():
                continue
            backfilled += int(mask.sum())
            if new_df[data_survivor].dtype != new_df[c].dtype:
                new_df[data_survivor] = new_df[data_survivor].astype(object)
            new_df.loc[mask, data_survivor] = new_df.loc[mask, c]

        dropped.update(c for c in group if c != data_survivor)
        if election.canonical_name != data_survivor:
            renames[data_survivor] = election.canonical_name

        resolutions.append(DuplicateResolution(
            group=group,
            data_survivor=data_survivor,
            canonical_name=election.canonical_name,
            rationale=f"{election.rationale} {selection}",
            dropped=[c for c in group if c != data_survivor],
            cells_backfilled=backfilled,
            cells_overwritten={k: v for k, v in overwritten.items() if v},
            values_lost={k: v for k, v in lost.items() if v},
        ))
        divergence_reports.extend(_divergence_reports(
            election.canonical_name, data_survivor, overwritten, lost, len(new_df)
        ))

    new_df = new_df.drop(columns=list(dropped))
    if renames:
        new_df = new_df.rename(columns=renames)

    new_payload = [
        p.model_copy(update={
            "column_name": renames.get(p.column_name, p.column_name),
            "related_columns": [renames.get(r, r) for r in p.related_columns if r not in dropped],
        })
        for p in state.payload
        if p.column_name not in dropped
    ]
    new_reports = [
        _rename_report(r, renames.get(r.column_name, r.column_name))
        for r in state.validation_reports
        if r.column_name not in dropped
    ] + divergence_reports
    survivor_changes = diff_values_only(
        df[[c for c in new_df.columns if c in df.columns]],
        new_df[[c for c in new_df.columns if c in df.columns]],
        "duplicate_column",
    )
    return state.model_copy(update={
        "dataset": new_df,
        "change_log": state.change_log + survivor_changes,
        "surviving_columns": list(new_df.columns),
        "payload": new_payload,
        "validation_reports": new_reports,
        "duplicate_resolutions": resolutions,
    })


def _elect_data_survivor(df: pd.DataFrame, group: list[str]) -> tuple[str, str]:
    others = set(group)
    measured = {c: s for c in group if (s := coherence_score(df, c, others)) is not None}
    if measured:
        best = max(score for score, _ in measured.values())
        leaders = [c for c in group if c in measured and measured[c][0] == best]
        if len(leaders) == 1:
            winner = leaders[0]
            score, predictor = measured[winner]
            runners = ", ".join(
                f"{c} {measured[c][0]:.2%}" for c in group if c in measured and c != winner
            )
            return winner, (
                f"Kept {winner}: it matches the value implied by {predictor} on {score:.2%} "
                f"of rows, against {runners}."
            )
    else:
        leaders = list(group)

    nan_counts = {c: int(df[c].isna().sum()) for c in leaders}
    survivor = min(leaders, key=lambda c: nan_counts[c])
    reason = (
        "no other column explains this one well enough to compare them"
        if not measured
        else "the group members agree with the rest of the table equally well"
    )
    return survivor, (
        f"Kept {survivor}: {reason}, so the column with the fewest missing values was "
        f"taken ({nan_counts[survivor]})."
    )


def _elect_canonical_name(
    group: list[str],
    chain,
    system: str,
    domain: str,
    baseline_columns: list[str],
    conventions,
    taken: set[str],
) -> _NameElection:
    conforming = [c for c in group if is_conforming(c, conventions)]
    if len(conforming) == 1:
        return _NameElection(
            canonical_name=conforming[0],
            rationale="Only group member conforming to the baseline naming convention.",
        )

    candidates = conforming or group
    election = _llm_pick(chain, system, candidates, domain, baseline_columns)
    name = election.canonical_name
    if not is_conforming(name, conventions):
        name = normalize_column_name(name, conventions)
    if name not in group:
        name = uniquify(name, taken - set(group))
    return _NameElection(canonical_name=name, rationale=election.rationale)


def _find_groups(columns: list[str], df: pd.DataFrame) -> list[list[str]]:
    parent = {c: c for c in columns}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i, a in enumerate(columns):
        for b in columns[i + 1:]:
            if _similarity(df[a], df[b]) >= _SIMILARITY_THRESHOLD:
                union(a, b)

    grouped: dict[str, list[str]] = defaultdict(list)
    for c in columns:
        grouped[find(c)].append(c)
    return list(grouped.values())


def _similarity(a: pd.Series, b: pd.Series) -> float:
    overlap = a.notna() & b.notna()
    if not overlap.any():
        return 0.0
    a_n = a[overlap].astype("string").str.strip().str.lower()
    b_n = b[overlap].astype("string").str.strip().str.lower()
    return max(float((a_n == b_n).mean()), _numeric_similarity(a[overlap], b[overlap]))


def _numeric_similarity(a: pd.Series, b: pd.Series) -> float:
    a_num = pd.to_numeric(a, errors="coerce")
    b_num = pd.to_numeric(b, errors="coerce")
    comparable = a_num.notna() & b_num.notna()
    if not comparable.any():
        return 0.0
    return float((a_num[comparable] == b_num[comparable]).mean()) * float(comparable.mean())


def _llm_pick(chain, system: str, group: list[str], domain: str, baseline_columns: list[str]) -> _NameElection:
    result: _NameElection = chain.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps({
            "duplicate_group": group,
            "domain": domain,
            "baseline_columns": baseline_columns,
        }, ensure_ascii=False)},
    ])
    if result.canonical_name not in group:
        return _NameElection(canonical_name=group[0], rationale=result.rationale)
    return result


def _baseline_columns_for_domain(state: PipelineState) -> list[str]:
    if state.baseline is None or not state.detected_domain:
        return []
    domain = state.baseline.domains.get(state.detected_domain)
    if domain is None:
        return []
    seen: dict[str, None] = {}
    for dataset in domain.datasets.values():
        for col_name in dataset.columns.keys():
            seen.setdefault(col_name, None)
    return list(seen.keys())


def _divergence(survivor: pd.Series, other: pd.Series) -> tuple[int, list]:
    comparable = survivor.notna() & other.notna()
    if not comparable.any():
        return 0, []
    differing = comparable & (survivor.astype(str) != other.astype(str))
    if not differing.any():
        return 0, []
    only_in_other = set(other[differing].astype(str)) - set(survivor.astype(str))
    return int(differing.sum()), sorted(only_in_other)[:_MAX_LOST_VALUES]


def _divergence_reports(
    canonical_name: str,
    survivor: str,
    overwritten: dict[str, int],
    lost: dict[str, list],
    rows: int,
) -> list[ValidationReport]:
    total = sum(overwritten.values())
    if not rows or total / rows <= _DIVERGENCE_ALERT_RATIO:
        return []
    return [ValidationReport(
        column_name=canonical_name,
        violations=[FormatViolation(
            column_name=canonical_name,
            row_index=-1,
            value=total,
            kind="schema",
            affected_rows=total,
            expected_pattern=(
                f"duplicate-column divergence: {survivor} differs from its siblings on "
                f"{total} cells ({total / rows:.1%}); values only present in the dropped "
                f"columns: {sorted({v for values in lost.values() for v in values})[:5]}"
            ),
        )],
    )]


def _rename_report(report: ValidationReport, name: str) -> ValidationReport:
    """A shallow model_copy renames the report but leaves the nested violations pointing at the
    old column, and hands back the same list object, so the original report changes whenever the
    copy does."""
    if name == report.column_name:
        return report
    return ValidationReport(
        column_name=name,
        detected_total=report.detected_total,
        violations=[v.model_copy(update={"column_name": name}) for v in report.violations],
    )
