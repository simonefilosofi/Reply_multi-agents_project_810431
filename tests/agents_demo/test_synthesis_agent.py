"""Unit tests for SynthesisAgent typed migration, conflict patterns, and
deliberation subgraph (Step 10).

Each test seeds the per-detector reports with typed Issue instances so we
exercise the synthesis logic without relying on Layer-1 detectors. The
``monkeypatch_llm`` fixture stubs LLM transport for the executive summary;
specialist votes and supervisor tie-breaks are stubbed via direct
attribute monkey-patching on :class:`SynthesisAgent`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from agents_demo.base_agent import BaseAgent
from agents_demo.synthesis_agent import SynthesisAgent
from state_demo import settings as live_settings
from state_demo.deliberation import SupervisorDecision, Vote
from state_demo.issues import (
    DomainNegativeValuesIssue,
    DuplicateColumnsIssue,
    InvalidDatesIssue,
    Issue,
    LookupImputabilityIssue,
    MixedTypeIssue,
    OutliersIssue,
)
from state_demo.pipeline_state import PipelineState


def _seed_empty_reports(state: PipelineState) -> None:
    for attr in (
        "schema_report",
        "completeness_report",
        "duplicate_report",
        "anomaly_report",
        "consistency_report",
        "constraint_report",
    ):
        setattr(state, attr, {"issues": [], "total_issues": 0})


def _seed_minimal_df(state: PipelineState, columns: list[str]) -> None:
    state.df_raw = pd.DataFrame({c: [1, 2, 3] for c in columns})


@pytest.fixture
def synthesis_state(state: PipelineState) -> PipelineState:
    _seed_empty_reports(state)
    state.dataset_fingerprint = {
        "domain": "test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": [],
        "categorical_columns": [],
        "date_columns": [],
        "sparse_columns": [],
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    state.completeness_by_column = {}
    state.overall_completeness = 1.0
    return state


def _stub_vote(*, keep_issue: bool, confidence: float = 0.9) -> Any:
    def _vote(self: SynthesisAgent, specialist_name: str, peer_name: str, contested: Issue) -> Vote:
        return Vote(
            agent_name=specialist_name,  # type: ignore[arg-type]
            keep_issue=keep_issue,
            rationale=f"stub vote: keep={keep_issue}",
            confidence=confidence,
        )

    return _vote


def _stub_supervisor(decision: str) -> Any:
    def _tie_break(self: SynthesisAgent, contested: Issue, votes: list[Vote]) -> SupervisorDecision:
        return SupervisorDecision(
            final_decision=decision,  # type: ignore[arg-type]
            rationale=f"stub supervisor: {decision}",
        )

    return _tie_break


def test_pattern_profiler_schema_date_dispute_demotes_column(
    synthesis_state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["periodo", "amount"])
    state.dataset_fingerprint["date_columns"] = ["periodo"]
    state.dataset_fingerprint["categorical_columns"] = []
    state.schema_report = {
        "issues": [
            InvalidDatesIssue(
                column="periodo",
                detail="parse rate too low",
                severity="high",
                source="schema",
                parse_rate=0.20,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"

    SynthesisAgent(state).run("synthesis")

    assert "periodo" not in state.dataset_fingerprint["date_columns"]
    assert "periodo" in state.dataset_fingerprint["categorical_columns"]
    demote_insights = [
        ins for ins in state.cross_agent_insights if "Demoting to categorical" in ins["insight"]
    ]
    assert demote_insights, "expected a date-dispute demotion insight"


def test_pattern_duplicate_vs_lookup_suppresses_duplicate(
    synthesis_state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["region_code", "regione_codice"])
    dup = DuplicateColumnsIssue(
        column="region_code / regione_codice",
        column_a="region_code",
        column_b="regione_codice",
        detail="value-overlap >= 0.85",
        severity="medium",
        source="duplicate",
    )
    state.duplicate_report = {"issues": [dup], "total_issues": 1}
    state.consistency_report = {
        "issues": [
            LookupImputabilityIssue(
                column="region_code",
                detail="mapping from regione_codice",
                severity="medium",
                source="consistency",
                mapping_source="regione_codice",
                coverage=0.95,
                n_imputable=10,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"

    SynthesisAgent(state).run("synthesis")

    dup_remaining = [i for i in state.prioritized_issues if i.type == "duplicate_columns"]
    assert not dup_remaining, "duplicate_columns issue must be suppressed"
    suppression = [
        ins
        for ins in state.cross_agent_insights
        if "Suppressed duplicate-columns drop" in ins["action_taken"]
    ]
    assert suppression, "expected a suppression insight in cross_agent_insights"
    assert state.duplicate_report["total_issues"] == 0


def test_pattern_outlier_vs_domain_negative_drop_removes_issue(
    synthesis_state: PipelineState,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["amount"])
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="amount",
                detail="3xIQR fence",
                severity="medium",
                source="anomaly",
                outlier_count=4,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="amount",
                detail="negative values present",
                severity="medium",
                source="constraint",
                negative_count=3,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"
    monkeypatch.setattr(
        SynthesisAgent, "_specialist_vote", _stub_vote(keep_issue=False, confidence=0.95)
    )

    SynthesisAgent(state).run("synthesis")

    decisions = [d.final_decision for d in state.deliberation_log]
    assert decisions, "deliberation_log must record at least one outcome"
    assert all(d == "drop" for d in decisions)
    remaining_types = {i.type for i in state.prioritized_issues}
    assert "outliers" not in remaining_types
    assert "domain_negative_values" not in remaining_types


def test_pattern_outlier_vs_domain_negative_keep_upgrades_severity(
    synthesis_state: PipelineState,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["amount"])
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="amount",
                detail="3xIQR fence",
                severity="medium",
                source="anomaly",
                outlier_count=4,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="amount",
                detail="negative values present",
                severity="medium",
                source="constraint",
                negative_count=3,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"
    monkeypatch.setattr(
        SynthesisAgent, "_specialist_vote", _stub_vote(keep_issue=True, confidence=0.9)
    )

    SynthesisAgent(state).run("synthesis")

    outcomes = state.deliberation_log
    assert all(o.final_decision == "keep" for o in outcomes)
    surviving = [
        i
        for i in state.prioritized_issues
        if i.type in ("outliers", "domain_negative_values") and i.column == "amount"
    ]
    assert surviving, "issues should still be present after keep"
    assert all(i.severity == "high" for i in surviving)


def test_deliberation_supervisor_tie_break(
    synthesis_state: PipelineState,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["amount"])
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="amount",
                detail="3xIQR fence",
                severity="medium",
                source="anomaly",
                outlier_count=4,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="amount",
                detail="negative values present",
                severity="medium",
                source="constraint",
                negative_count=3,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"

    def _split_vote(
        self: SynthesisAgent, specialist_name: str, peer_name: str, contested: Issue
    ) -> Vote:
        keep = specialist_name == "anomaly"
        return Vote(
            agent_name=specialist_name,  # type: ignore[arg-type]
            keep_issue=keep,
            rationale=f"split vote, {specialist_name}={keep}",
            confidence=0.6,
        )

    monkeypatch.setattr(SynthesisAgent, "_specialist_vote", _split_vote)
    monkeypatch.setattr(SynthesisAgent, "_supervisor_tie_break", _stub_supervisor("escalate"))

    SynthesisAgent(state).run("synthesis")

    outcomes = state.deliberation_log
    assert outcomes, "deliberation_log must record outcomes"
    assert any(o.final_decision == "escalate" for o in outcomes)


def test_deliberation_disabled_skips_loop(
    synthesis_state: PipelineState,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["amount"])
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="amount",
                detail="3xIQR fence",
                severity="medium",
                source="anomaly",
                outlier_count=4,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="amount",
                detail="negative values present",
                severity="medium",
                source="constraint",
                negative_count=3,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"

    def _should_not_be_called(*args: Any, **kwargs: Any) -> Vote:
        raise AssertionError("specialist vote must not be called when deliberation is disabled")

    monkeypatch.setattr(SynthesisAgent, "_specialist_vote", _should_not_be_called)
    monkeypatch.setattr(live_settings.pipeline, "enable_deliberation", False)

    SynthesisAgent(state).run("synthesis")

    assert state.deliberation_log == []
    types = {i.type for i in state.prioritized_issues}
    assert types == {"outliers", "domain_negative_values"}


def test_existing_profiler_schema_mixed_type_conflict_is_preserved(
    synthesis_state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["amount"])
    state.dataset_fingerprint["numerical_columns"] = ["amount"]
    state.schema_report = {
        "issues": [
            MixedTypeIssue(
                column="amount",
                detail="mostly non-numeric",
                severity="high",
                source="schema",
                numeric_count=2,
                non_numeric_count=18,
            )
        ],
        "total_issues": 1,
    }
    monkeypatch_llm["call_llm"] = "stub summary"

    SynthesisAgent(state).run("synthesis")

    insights = [
        ins
        for ins in state.cross_agent_insights
        if "Review column classification" in ins["action_taken"]
    ]
    assert insights, "the existing profiler-vs-schema mixed_type insight must still fire"


def test_deliberation_handles_llm_failure_gracefully(
    synthesis_state: PipelineState,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = synthesis_state
    _seed_minimal_df(state, ["amount"])
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="amount",
                detail="3xIQR fence",
                severity="medium",
                source="anomaly",
                outlier_count=4,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="amount",
                detail="negative values present",
                severity="medium",
                source="constraint",
                negative_count=3,
            )
        ],
        "total_issues": 1,
    }

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("offline")

    monkeypatch.setattr(BaseAgent, "call_llm", _raise)
    monkeypatch.setattr(BaseAgent, "call_llm_json", _raise)

    SynthesisAgent(state).run("synthesis")

    types = {i.type for i in state.prioritized_issues}
    assert "outliers" in types and "domain_negative_values" in types
    assert all(o.final_decision == "keep" for o in state.deliberation_log)
