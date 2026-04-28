"""End-to-end integration test for the synthesis deliberation loop (Step 10).

Drives a wide_dirty-style fixture through ConsistencyAgent / ConstraintAgent /
AnomalyAgent / DuplicateAgent, then SynthesisAgent. The fixture is augmented
with a numeric column carrying both negative-and-outlier values so the
outlier-vs-domain-negative deliberation pattern fires deterministically. The
specialist vote and tie-break are stubbed so the test stays offline; the
assertion is that ``state.deliberation_log`` records at least one outcome and
that the synthesis pipeline still completes without LLM access.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents_demo.synthesis_agent import SynthesisAgent
from state_demo.deliberation import Vote
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


def _wide_state(wide_dirty_df: pd.DataFrame) -> PipelineState:
    state = PipelineState()
    df = wide_dirty_df.copy()
    rng = np.random.default_rng(42)
    n = len(df)
    base = rng.normal(loc=200.0, scale=30.0, size=n)
    base[: max(1, int(n * 0.05))] = -1500.0
    df["delta_amount"] = base
    state.df_raw = df
    state.dataset_fingerprint = {
        "domain": "noipa_test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": ["delta_amount", "importo_lordo", "importo_netto"],
        "categorical_columns": ["region_code", "regione_codice", "capoluogo"],
        "date_columns": [],
        "sparse_columns": ["sparse_a", "sparse_b"],
        "likely_duplicate_pairs": [
            ["region_code", "regione_codice"],
            ["importo_lordo", "importo_netto"],
        ],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    state.completeness_by_column = {c: 1.0 for c in df.columns}
    state.overall_completeness = 1.0

    state.schema_report = {
        "issues": [
            MixedTypeIssue(
                column="delta_amount",
                detail="mixed type sample",
                severity="medium",
                source="schema",
            ),
            InvalidDatesIssue(
                column="region_code",
                detail="profiler-vs-schema date dispute fixture",
                severity="medium",
                source="schema",
                parse_rate=0.10,
            ),
        ],
        "total_issues": 2,
    }
    state.dataset_fingerprint["date_columns"] = ["region_code"]
    state.completeness_report = {"issues": [], "total_issues": 0}
    state.duplicate_report = {
        "issues": [
            DuplicateColumnsIssue(
                column="region_code / regione_codice",
                column_a="region_code",
                column_b="regione_codice",
                detail="duplicate region columns",
                severity="medium",
                source="duplicate",
            )
        ],
        "total_issues": 1,
    }
    state.consistency_report = {
        "issues": [
            LookupImputabilityIssue(
                column="region_code",
                detail="capoluogo -> region_code mapping",
                severity="medium",
                source="consistency",
                mapping_source="regione_codice",
                coverage=0.95,
                n_imputable=20,
            )
        ],
        "total_issues": 1,
    }
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="delta_amount",
                detail="3xIQR outliers",
                severity="medium",
                source="anomaly",
                outlier_count=10,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="delta_amount",
                detail="negative values in non-negative column",
                severity="medium",
                source="constraint",
                negative_count=10,
            )
        ],
        "total_issues": 1,
    }
    return state


def test_synthesis_deliberation_logs_outcome_on_wide_dirty(
    wide_dirty_df: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state = _wide_state(wide_dirty_df)
    monkeypatch_llm["call_llm"] = "stub summary"

    def _vote(self: SynthesisAgent, specialist_name: str, peer_name: str, contested: Issue) -> Vote:
        keep = specialist_name == contested.source
        return Vote(
            agent_name=specialist_name,  # type: ignore[arg-type]
            keep_issue=keep,
            rationale=f"e2e stub vote: {specialist_name} keep={keep}",
            confidence=0.85,
        )

    monkeypatch.setattr(SynthesisAgent, "_specialist_vote", _vote)

    SynthesisAgent(state).run("synthesis")

    assert state.deliberation_log, "expected at least one deliberation outcome"
    contested_columns = {o.contested_issue.column for o in state.deliberation_log}
    assert "delta_amount" in contested_columns
    assert state.dataset_fingerprint["date_columns"] == [], (
        "profiler-vs-schema date dispute must demote 'region_code'"
    )
    assert "region_code" in state.dataset_fingerprint["categorical_columns"]
    dup_remaining = [i for i in state.prioritized_issues if i.type == "duplicate_columns"]
    assert not dup_remaining, "duplicate_columns must be suppressed by lookup overlap"
    assert state.synthesis_summary, "synthesis_summary must be populated"
