"""End-to-end regression test for B1 (format_pattern_violation pattern loss).

Demonstrates that a ``format_pattern`` constraint defined by the profiler
reaches the remediation agent with its ``pattern`` field intact. Before
Step 9 the ``pattern`` key could silently disappear between detection (dict
emitted by ``tools.check_format_pattern``) and remediation (dict consumed
by ``RemediationAgent``). After Step 9 the pattern is structurally enforced
by ``FormatPatternViolationIssue.pattern`` so the field cannot be lost.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo._enrichment import EnrichmentResponse
from agents_demo.constraint_agent import ConstraintAgent
from agents_demo.remediation_agent import RemediationAgent
from agents_demo.synthesis_agent import SynthesisAgent
from state_demo.issues import FormatPatternViolationIssue
from state_demo.pipeline_state import PipelineState


def test_format_pattern_pattern_field_survives_to_remediation(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame(
        {
            "periodo": [
                "202401",
                "202402",
                "202403",
                "202404",
                "202405",
                "BAD",
                "garbage",
                "x",
                "202406",
                "202407",
            ],
            "amount": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0],
        }
    )
    state.df_raw = df
    state.dataset_fingerprint = {
        "domain": "test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": ["amount"],
        "categorical_columns": ["periodo"],
        "date_columns": [],
        "sparse_columns": [],
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [
            {
                "column": "periodo",
                "type": "format_pattern",
                "pattern": r"^\d{6}$",
                "description": "YYYYMM period code",
            }
        ],
    }
    state.schema_report = {"issues": [], "total_issues": 0}
    state.completeness_report = {"issues": [], "total_issues": 0}
    state.duplicate_report = {"issues": [], "total_issues": 0}
    state.anomaly_report = {"issues": [], "total_issues": 0}
    state.consistency_report = {"issues": [], "total_issues": 0}
    monkeypatch_llm["call_llm_json"] = EnrichmentResponse(issues=[])

    ConstraintAgent(state).run("constraint")

    typed_issues = state.constraint_report["issues"]
    pattern_issues = [i for i in typed_issues if isinstance(i, FormatPatternViolationIssue)]
    assert pattern_issues, "ConstraintAgent must emit a FormatPatternViolationIssue"
    assert pattern_issues[0].pattern == r"^\d{6}$"
    assert pattern_issues[0].description == "YYYYMM period code"

    SynthesisAgent(state).run("synthesis")

    prioritized_pattern = [
        issue
        for issue in state.prioritized_issues
        if issue.get("type") == "format_pattern_violation"
    ]
    assert prioritized_pattern, "synthesis must keep format_pattern_violation in prioritized_issues"
    assert prioritized_pattern[0].get("pattern") == r"^\d{6}$", (
        "pattern field must survive synthesis -> remediation handoff"
    )

    RemediationAgent(state).run("remediation")

    fix_entries = [
        f
        for f in state.fix_log
        if f["issue_type"] == "format_pattern_violation" and f["action"] == "auto_fixed"
    ]
    assert fix_entries, (
        "RemediationAgent must auto-fix format_pattern_violation when pattern is present"
    )
    assert "format pattern" in fix_entries[0]["description"].lower()
