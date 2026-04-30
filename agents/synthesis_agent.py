"""Layer 2 synthesis / supervisor agent.

Collects typed :class:`Issue` instances from every Layer 1 detector,
runs cross-agent convergence analysis, detects four named inter-agent
conflict patterns (profiler-vs-schema mixed_type, profiler-vs-schema
date dispute, duplicate-vs-lookup, outlier-vs-domain-negative), invokes
a LangGraph deliberation subgraph for each contested issue routed by
pattern 4, recalibrates severity from compounding evidence, computes
the pre-remediation reliability score on the consolidated finding set,
and emits an executive summary. The deliberation loop is gated by
``Settings.pipeline.enable_deliberation`` so fast runs can skip it.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from functools import cache
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic_ai.exceptions import ModelHTTPError

from agents_demo.base_agent import SMART, BaseAgent
from state import settings as default_settings
from state.agent_names import AgentName
from state.constants import SEVERITY_RANK
from state.deliberation import (
    DeliberationOutcome,
    FinalDecision,
    SupervisorDecision,
    Vote,
)
from state.issues import (
    DomainNegativeValuesIssue,
    DuplicateColumnsIssue,
    InvalidDatesIssue,
    Issue,
    LookupImputabilityIssue,
    MixedTypeIssue,
    OutliersIssue,
)
from state.scoring import compute_reliability_score

VoteCaller = Callable[[AgentName, AgentName, Issue], Vote]
SupervisorTieBreaker = Callable[[Issue, list[Vote]], SupervisorDecision]

DELIBERATION_PAIR_CAP = 5
SEVERITY_UPGRADE_CONFIDENCE = 0.7


class _DeliberationStateDict(TypedDict, total=False):
    contested_issue: Issue
    specialist_a_name: AgentName
    specialist_b_name: AgentName
    vote_caller: VoteCaller
    supervisor_tie_breaker: SupervisorTieBreaker
    votes: Annotated[list[Vote], operator.add]
    final_decision: FinalDecision
    rationale: str


def _specialist_a_node(state: _DeliberationStateDict) -> dict[str, Any]:
    vote = state["vote_caller"](
        state["specialist_a_name"],
        state["specialist_b_name"],
        state["contested_issue"],
    )
    return {"votes": [vote]}


def _specialist_b_node(state: _DeliberationStateDict) -> dict[str, Any]:
    vote = state["vote_caller"](
        state["specialist_b_name"],
        state["specialist_a_name"],
        state["contested_issue"],
    )
    return {"votes": [vote]}


def _tally_node(state: _DeliberationStateDict) -> dict[str, Any]:
    votes = list(state.get("votes", []))
    if not votes:
        return {"final_decision": "escalate", "rationale": "No specialist votes were recorded."}
    keep_votes = [v for v in votes if v.keep_issue]
    drop_votes = [v for v in votes if not v.keep_issue]
    if not drop_votes:
        rationale = " | ".join(v.rationale.strip() for v in keep_votes if v.rationale.strip())
        return {
            "final_decision": "keep",
            "rationale": rationale or "Specialists unanimously voted to keep the issue.",
        }
    if not keep_votes:
        rationale = " | ".join(v.rationale.strip() for v in drop_votes if v.rationale.strip())
        return {
            "final_decision": "drop",
            "rationale": rationale or "Specialists unanimously voted to drop the issue.",
        }
    decision = state["supervisor_tie_breaker"](state["contested_issue"], votes)
    return {"final_decision": decision.final_decision, "rationale": decision.rationale}


@cache
def _build_deliberation_subgraph(
    specialist_a_name: AgentName,
    specialist_b_name: AgentName,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph: StateGraph[Any, Any, Any, Any] = StateGraph(_DeliberationStateDict)
    graph.add_node("specialist_a_vote", _specialist_a_node)
    graph.add_node("specialist_b_vote", _specialist_b_node)
    graph.add_node("tally", _tally_node)
    graph.add_edge(START, "specialist_a_vote")
    graph.add_edge(START, "specialist_b_vote")
    graph.add_edge("specialist_a_vote", "tally")
    graph.add_edge("specialist_b_vote", "tally")
    graph.add_edge("tally", END)
    return graph.compile()


def _issue_card(issue: Issue) -> str:
    fields = ["type", "column", "severity", "source", "detail"]
    parts = []
    for f in fields:
        value = issue.get(f)
        if value is None:
            continue
        parts.append(f"{f}={value!r}")
    return ", ".join(parts)


class SynthesisAgent(BaseAgent):
    name = "synthesis"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a data quality synthesis supervisor. Your role is to review "
        "findings from multiple specialized agents, identify cross-cutting patterns "
        "and root causes, detect inter-agent conflicts, and generate executive-level "
        "summaries of data quality findings. When performing cross-agent analysis, "
        "be analytical and concise. For executive summaries, write 4-6 sentences "
        "highlighting the most critical problems and their business impact."
    )

    def think(self) -> None:
        self.log("think", self.prompt)

    def act(self) -> None:
        all_issues = self._gather_typed_issues()
        all_issues.sort(key=lambda i: SEVERITY_RANK.get(i.severity, 2))
        self.state.prioritized_issues = all_issues

        column_issues: dict[str, list[Issue]] = {}
        for issue in all_issues:
            column_issues.setdefault(issue.column or "", []).append(issue)

        self._column_convergence_analysis(column_issues)
        contested = self._conflict_detection()
        self._severity_recalibration(column_issues)
        self._run_deliberation(contested)

    def observe(self) -> None:
        score, dimensions = compute_reliability_score(self.state.df_raw, self.state)
        self.state.reliability_score_before = score
        self.state.dimension_trajectory["post_synthesis"] = dict(dimensions)
        issues = self.state.prioritized_issues
        high = sum(1 for i in issues if i.severity == "high")
        medium = sum(1 for i in issues if i.severity == "medium")
        low = sum(1 for i in issues if i.severity == "low")
        dim_text = ", ".join(f"{k}={v:.2f}" for k, v in dimensions.items())
        self.log(
            "observe",
            f"{len(issues)} issues prioritized: "
            f"{high} high, {medium} medium, {low} low. "
            f"Pre-remediation reliability score: {score}/100 ({dim_text})",
        )

    def reply(self) -> None:
        all_issues = self.state.prioritized_issues
        sources = {i.source for i in all_issues if i.source}
        top = all_issues[:10]
        top_text = (
            "\n".join(f"- [{i.severity.upper()}] ({i.source}) {i.column}: {i.detail}" for i in top)
            or "No issues found."
        )
        summaries = "\n".join(
            filter(
                None,
                [
                    self.state.schema_summary,
                    self.state.completeness_summary,
                    self.state.duplicate_summary,
                    self.state.anomaly_summary,
                    self.state.consistency_summary,
                    self.state.constraint_summary,
                ],
            )
        )
        insights_text = (
            "\n".join(
                f"- {ins['insight']}: {ins['action_taken']}"
                for ins in self.state.cross_agent_insights
            )
            or "No cross-agent insights."
        )
        deliberation_text = (
            "\n".join(
                f"- {d.contested_issue.type}@{d.contested_issue.column}: "
                f"{d.final_decision} ({d.rationale})"
                for d in self.state.deliberation_log
            )
            or "No deliberation outcomes."
        )

        user = (
            f"Task: {self.prompt}\n\n"
            f"Dataset domain: "
            f"{self.state.dataset_fingerprint.get('domain', 'unknown')}\n"
            f"Total issues found: {len(all_issues)}\n"
            f"Pre-remediation reliability score: "
            f"{self.state.reliability_score_before}/100\n\n"
            f"Top issues:\n{top_text}\n\n"
            f"Agent summaries:\n{summaries}\n\n"
            f"Cross-agent insights:\n{insights_text}\n\n"
            f"Deliberation outcomes:\n{deliberation_text}\n\n"
            f"Write a concise executive summary (4-6 sentences) highlighting "
            f"the most critical problems and their business impact."
        )
        try:
            self.state.synthesis_summary = self.call_llm(user).strip()
        except Exception as exc:
            self.log("error", str(exc))
            self.state.synthesis_summary = (
                f"{len(all_issues)} issues found across {len(sources)} agents. "
                f"Pre-remediation reliability score: "
                f"{self.state.reliability_score_before:.1f}/100."
            )
        self.log("reply", self.state.synthesis_summary)

    def _gather_typed_issues(self) -> list[Issue]:
        sources: tuple[tuple[AgentName, Any], ...] = (
            ("schema", self.state.schema_report),
            ("completeness", self.state.completeness_report),
            ("duplicate", self.state.duplicate_report),
            ("anomaly", self.state.anomaly_report),
            ("consistency", self.state.consistency_report),
            ("constraint", self.state.constraint_report),
        )
        out: list[Issue] = []
        for source, report in sources:
            for issue in report.get("issues", []):
                if issue.source is None:
                    issue = issue.model_copy(update={"source": source})
                out.append(issue)
        return out

    def _column_convergence_analysis(self, column_issues: dict[str, list[Issue]]) -> None:
        multi_agent_cols = {
            col: issues
            for col, issues in column_issues.items()
            if col and len({i.source for i in issues if i.source}) >= 2
        }
        if len(multi_agent_cols) > DELIBERATION_PAIR_CAP:
            sorted_cols = sorted(
                multi_agent_cols,
                key=lambda c: min(SEVERITY_RANK.get(i.severity, 2) for i in multi_agent_cols[c]),
            )
            multi_agent_cols = {c: multi_agent_cols[c] for c in sorted_cols[:DELIBERATION_PAIR_CAP]}

        for col, issues in multi_agent_cols.items():
            agents_involved = sorted({i.source for i in issues if i.source})
            agent_labels = [f"{a.title()}Agent" for a in agents_involved]
            issue_lines = "\n".join(
                f"  - {(i.source or '').title()}Agent: {i.detail}" for i in issues
            )
            self.log(
                "act",
                f"Querying {' and '.join(agent_labels)} about "
                f"column '{col}': {len(agents_involved)} agents "
                f"flagged issues that may share a root cause.",
            )

            user = (
                f"Column '{col}' was flagged by multiple agents:\n{issue_lines}\n\n"
                f"Reason about whether these findings share a root cause. "
                f"Respond ONLY with a JSON object, no other text: "
                f'{{"root_cause": "...", "recommendation": "..."}}'
            )
            try:
                result = self.call_llm_json(user, max_tokens=512)
                root_cause = result.get("root_cause", "undetermined")
                recommendation = result.get("recommendation", "manual review")
            except Exception as exc:
                self.log("error", f"LLM cross-agent analysis failed for '{col}': {exc}")
                root_cause = "Multiple quality dimensions affected -- manual review recommended."
                recommendation = "Inspect column in source system."

            insight = {
                "insight": (
                    f"Column '{col}' flagged by {len(agents_involved)} agents: {root_cause}"
                ),
                "related_agents": agents_involved,
                "related_columns": [col],
                "action_taken": recommendation,
            }
            self.state.cross_agent_insights.append(insight)
            self.log("act", f"Cross-reference result for column '{col}': {root_cause}")

    def _conflict_detection(self) -> list[Issue]:
        contested: list[Issue] = []
        self._detect_profiler_schema_mixed_type()
        self._detect_profiler_schema_date_dispute()
        self._detect_duplicate_vs_lookup()
        contested.extend(self._detect_outlier_vs_domain_negative())
        return contested

    def _detect_profiler_schema_mixed_type(self) -> None:
        fp = self.state.dataset_fingerprint
        num_cols = set(fp.get("numerical_columns", []))
        for issue in self.state.schema_report.get("issues", []):
            if (
                isinstance(issue, MixedTypeIssue)
                and issue.column in num_cols
                and issue.severity == "high"
            ):
                detail = (
                    f"Conflict: ProfilerAgent classified '{issue.column}' as "
                    f"numerical, but SchemaAgent found it mostly non-numeric "
                    f"({issue.detail}). Column classification may need revision."
                )
                self.log("act", detail)
                self.state.cross_agent_insights.append(
                    {
                        "insight": detail,
                        "related_agents": ["profiler", "schema"],
                        "related_columns": [issue.column],
                        "action_taken": "Review column classification",
                    }
                )

    def _detect_profiler_schema_date_dispute(self) -> None:
        fp = self.state.dataset_fingerprint
        date_cols = list(fp.get("date_columns", []) or [])
        if not date_cols:
            return
        cat_cols = list(fp.get("categorical_columns", []) or [])
        demoted: list[str] = []
        for issue in self.state.schema_report.get("issues", []):
            if not isinstance(issue, InvalidDatesIssue):
                continue
            if issue.column not in date_cols:
                continue
            parse_rate = issue.parse_rate
            if parse_rate is None or parse_rate >= 0.5:
                continue
            if issue.column in demoted:
                continue
            date_cols.remove(issue.column)
            if issue.column not in cat_cols:
                cat_cols.append(issue.column)
            demoted.append(issue.column)
            detail = (
                f"Conflict: ProfilerAgent classified '{issue.column}' as a date "
                f"column, but SchemaAgent measured parse_rate="
                f"{parse_rate:.2f} (<0.50). Demoting to categorical."
            )
            self.log("act", detail)
            self.state.cross_agent_insights.append(
                {
                    "insight": detail,
                    "related_agents": ["profiler", "schema"],
                    "related_columns": [issue.column],
                    "action_taken": "Demoted to categorical_columns in fingerprint.",
                }
            )
        if demoted:
            fp["date_columns"] = date_cols
            fp["categorical_columns"] = cat_cols

    def _detect_duplicate_vs_lookup(self) -> None:
        dup_issues = [
            i
            for i in self.state.duplicate_report.get("issues", [])
            if isinstance(i, DuplicateColumnsIssue)
        ]
        lookup_issues = [
            i
            for i in self.state.consistency_report.get("issues", [])
            if isinstance(i, LookupImputabilityIssue)
        ]
        if not dup_issues or not lookup_issues:
            return
        lookup_pairs: set[tuple[str, str]] = set()
        for li in lookup_issues:
            if li.column and li.mapping_source:
                lookup_pairs.add((li.column, li.mapping_source))
                lookup_pairs.add((li.mapping_source, li.column))
        if not lookup_pairs:
            return
        suppressed: list[DuplicateColumnsIssue] = []
        for dup in dup_issues:
            pair = (dup.column_a, dup.column_b)
            if pair in lookup_pairs or (pair[1], pair[0]) in lookup_pairs:
                suppressed.append(dup)
        if not suppressed:
            return
        suppressed_ids = {id(i) for i in suppressed}
        self.state.prioritized_issues = [
            i for i in self.state.prioritized_issues if id(i) not in suppressed_ids
        ]
        kept: list[Issue] = [
            i for i in self.state.duplicate_report["issues"] if id(i) not in suppressed_ids
        ]
        self.state.duplicate_report = {"issues": kept, "total_issues": len(kept)}
        for dup in suppressed:
            detail = (
                f"Conflict: DuplicateAgent flagged '{dup.column_a}' / "
                f"'{dup.column_b}' as duplicate columns, but ConsistencyAgent "
                f"found a lookup-imputability mapping between them. Both columns "
                f"are kept; duplicate-drop fix suppressed."
            )
            self.log("act", detail)
            self.state.cross_agent_insights.append(
                {
                    "insight": detail,
                    "related_agents": ["duplicate", "consistency"],
                    "related_columns": [dup.column_a, dup.column_b],
                    "action_taken": "Suppressed duplicate-columns drop.",
                }
            )

    def _detect_outlier_vs_domain_negative(self) -> list[Issue]:
        outlier_by_col: dict[str, OutliersIssue] = {
            i.column: i
            for i in self.state.anomaly_report.get("issues", [])
            if isinstance(i, OutliersIssue)
        }
        domneg_by_col: dict[str, DomainNegativeValuesIssue] = {
            i.column: i
            for i in self.state.constraint_report.get("issues", [])
            if isinstance(i, DomainNegativeValuesIssue)
        }
        contested: list[Issue] = []
        shared_cols = sorted(set(outlier_by_col) & set(domneg_by_col))
        for col in shared_cols:
            outlier = outlier_by_col[col]
            domneg = domneg_by_col[col]
            for issue in (outlier, domneg):
                if issue.severity != "high":
                    issue.severity = "high"
            detail = (
                f"Conflict: AnomalyAgent flagged '{col}' as outliers and "
                f"ConstraintAgent flagged the same column as "
                f"domain_negative_values. Severity upgraded to high; routed "
                f"to deliberation."
            )
            self.log("act", detail)
            self.state.cross_agent_insights.append(
                {
                    "insight": detail,
                    "related_agents": ["anomaly", "constraint"],
                    "related_columns": [col],
                    "action_taken": "Routed to deliberation subgraph.",
                }
            )
            contested.extend([outlier, domneg])
        return contested

    def _severity_recalibration(self, column_issues: dict[str, list[Issue]]) -> None:
        for col, issues in column_issues.items():
            if not col:
                continue
            medium_issues = [i for i in issues if i.severity == "medium"]
            medium_agents = {i.source for i in medium_issues if i.source}
            if len(medium_agents) >= 2:
                for issue in medium_issues:
                    issue.severity = "high"
                self.log(
                    "act",
                    f"Severity recalibrated: '{col}' has medium issues from "
                    f"{len(medium_agents)} different agents "
                    f"({', '.join(sorted(medium_agents))}) -- upgraded to high",
                )
        self.state.prioritized_issues.sort(key=lambda i: SEVERITY_RANK.get(i.severity, 2))

    def _run_deliberation(self, contested: list[Issue]) -> None:
        if not contested:
            return
        if not default_settings.pipeline.enable_deliberation:
            self.log(
                "act",
                f"Deliberation disabled by settings; {len(contested)} contested issue(s) skipped.",
            )
            return

        full_pass = contested[:DELIBERATION_PAIR_CAP]
        batched = contested[DELIBERATION_PAIR_CAP:]
        outcomes: list[DeliberationOutcome] = []

        for issue in full_pass:
            outcome = self._deliberate(issue)
            if outcome is None:
                continue
            outcomes.append(outcome)

        if batched:
            outcomes.extend(self._batched_supervisor_deliberation(batched))

        for outcome in outcomes:
            self.state.deliberation_log.append(outcome)
            self._apply_deliberation(outcome)

        self.state.prioritized_issues.sort(key=lambda i: SEVERITY_RANK.get(i.severity, 2))

    def _deliberate(self, contested: Issue) -> DeliberationOutcome | None:
        peer = self._peer_agent_for(contested)
        specialist_a: AgentName = contested.source or "synthesis"
        specialist_b: AgentName = peer
        graph = _build_deliberation_subgraph(specialist_a, specialist_b)
        try:
            final = graph.invoke(
                {
                    "contested_issue": contested,
                    "specialist_a_name": specialist_a,
                    "specialist_b_name": specialist_b,
                    "vote_caller": self._specialist_vote,
                    "supervisor_tie_breaker": self._supervisor_tie_break,
                }
            )
        except ModelHTTPError as exc:
            self.log(
                "error",
                f"LLM unavailable during deliberation on "
                f"{contested.type}@{contested.column}: {exc}; keeping issue as-is.",
            )
            return None
        except Exception as exc:
            self.log(
                "error",
                f"Deliberation failed on {contested.type}@{contested.column}: {exc}; "
                f"keeping issue as-is.",
            )
            return None
        votes = list(final.get("votes", []))
        decision = final.get("final_decision", "escalate")
        rationale = final.get("rationale", "")
        outcome = DeliberationOutcome(
            contested_issue=contested,
            votes=votes,
            final_decision=decision,
            rationale=rationale,
        )
        self.log(
            "act",
            f"Deliberation on {contested.type}@{contested.column}: "
            f"{decision} ({len(votes)} vote(s)).",
        )
        return outcome

    def _batched_supervisor_deliberation(self, contested: list[Issue]) -> list[DeliberationOutcome]:
        cards = "\n".join(f"- [{idx}] {_issue_card(i)}" for idx, i in enumerate(contested))
        user = (
            "Several contested issues remain after the per-issue deliberation cap. "
            "Decide independently for each whether to keep, drop, or escalate it. "
            "Respond ONLY with a JSON object of the form "
            '{"decisions": [{"index": <int>, "final_decision": "keep|drop|escalate", '
            '"rationale": "..."}]}.\n\n'
            f"Contested issues:\n{cards}"
        )
        try:
            result = self.call_llm_json(user, max_tokens=1024)
        except Exception as exc:
            self.log(
                "error",
                f"Batched supervisor deliberation failed: {exc}; "
                f"keeping {len(contested)} contested issue(s) as-is.",
            )
            return []
        decisions = result.get("decisions", []) if isinstance(result, dict) else []
        outcomes: list[DeliberationOutcome] = []
        for entry in decisions:
            if not isinstance(entry, dict):
                continue
            idx = entry.get("index")
            if not isinstance(idx, int) or not 0 <= idx < len(contested):
                continue
            decision = entry.get("final_decision")
            if decision not in ("keep", "drop", "escalate"):
                continue
            rationale = str(entry.get("rationale", "")).strip() or "Batched supervisor decision."
            outcomes.append(
                DeliberationOutcome(
                    contested_issue=contested[idx],
                    votes=[],
                    final_decision=decision,
                    rationale=rationale,
                )
            )
        self.log(
            "act",
            f"Batched supervisor deliberation: {len(outcomes)} decision(s) "
            f"for {len(contested)} contested issue(s).",
        )
        return outcomes

    def _peer_agent_for(self, contested: Issue) -> AgentName:
        if isinstance(contested, OutliersIssue):
            return "constraint"
        if isinstance(contested, DomainNegativeValuesIssue):
            return "anomaly"
        return "synthesis"

    def _specialist_vote(
        self,
        specialist_name: AgentName,
        peer_name: AgentName,
        contested_issue: Issue,
    ) -> Vote:
        user = (
            f"You are the {specialist_name} agent in a multi-agent data quality "
            f"pipeline. You previously flagged the following issue:\n\n"
            f"  {_issue_card(contested_issue)}\n\n"
            f"The peer agent ({peer_name}) flagged the same column with a different "
            f"framing. Re-evaluate whether your finding should be kept. "
            f"Respond ONLY with JSON of the form "
            f'{{"agent_name": "{specialist_name}", "keep_issue": true|false, '
            f'"rationale": "...", "confidence": <float in [0, 1]>}}.'
        )
        try:
            response = self.call_llm_json(user, max_tokens=512, schema=Vote)
        except Exception as exc:
            self.log(
                "error",
                f"Specialist vote ({specialist_name}) failed for "
                f"{contested_issue.type}@{contested_issue.column}: {exc}; "
                f"defaulting to keep with low confidence.",
            )
            return Vote(
                agent_name=specialist_name,
                keep_issue=True,
                rationale=f"LLM unavailable during deliberation: {exc}.",
                confidence=0.0,
            )
        if isinstance(response, Vote):
            return response
        return Vote.model_validate(response)

    def _supervisor_tie_break(
        self,
        contested_issue: Issue,
        votes: list[Vote],
    ) -> SupervisorDecision:
        votes_text = "\n".join(
            f"- {v.agent_name}: keep={v.keep_issue} "
            f"(confidence={v.confidence:.2f}) -- {v.rationale}"
            for v in votes
        )
        user = (
            f"You are the synthesis supervisor. Two specialist agents disagreed on "
            f"whether to keep this contested issue:\n\n"
            f"  {_issue_card(contested_issue)}\n\n"
            f"Specialist votes:\n{votes_text}\n\n"
            f"Decide one of keep, drop, escalate. Respond ONLY with JSON of the form "
            '{"final_decision": "keep|drop|escalate", "rationale": "..."}.'
        )
        try:
            response = self.call_llm_json(user, max_tokens=512, schema=SupervisorDecision)
        except Exception as exc:
            self.log(
                "error",
                f"Supervisor tie-break failed for "
                f"{contested_issue.type}@{contested_issue.column}: {exc}; "
                f"defaulting to escalate.",
            )
            return SupervisorDecision(
                final_decision="escalate",
                rationale=f"LLM unavailable during tie-break: {exc}.",
            )
        if isinstance(response, SupervisorDecision):
            return response
        return SupervisorDecision.model_validate(response)

    def _apply_deliberation(self, outcome: DeliberationOutcome) -> None:
        contested = outcome.contested_issue
        if outcome.final_decision == "drop":
            target_id = id(contested)
            self.state.prioritized_issues = [
                i for i in self.state.prioritized_issues if id(i) != target_id
            ]
            self._remove_from_source_report(contested)
            return
        if outcome.final_decision == "keep":
            high_conf_keep = any(
                v.keep_issue and v.confidence >= SEVERITY_UPGRADE_CONFIDENCE for v in outcome.votes
            )
            if high_conf_keep and contested.severity != "high":
                contested.severity = "high"
                self.log(
                    "act",
                    f"Deliberation upgraded severity to high for "
                    f"{contested.type}@{contested.column} "
                    f"(at least one specialist kept the issue with confidence "
                    f">= {SEVERITY_UPGRADE_CONFIDENCE}).",
                )
            return
        # escalate: keep the issue but ensure it surfaces for human review
        if contested.severity != "high":
            contested.severity = "high"
        self.log(
            "act",
            f"Deliberation escalated {contested.type}@{contested.column} for human review.",
        )

    def _remove_from_source_report(self, contested: Issue) -> None:
        source = contested.source
        if source not in (
            "schema",
            "completeness",
            "duplicate",
            "anomaly",
            "consistency",
            "constraint",
        ):
            return
        attr = f"{source}_report"
        report = getattr(self.state, attr, None)
        if not report:
            return
        target_id = id(contested)
        kept = [i for i in report.get("issues", []) if id(i) != target_id]
        setattr(self.state, attr, {"issues": kept, "total_issues": len(kept)})
