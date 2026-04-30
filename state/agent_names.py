"""Closed registry of agent identifiers used across the pipeline.

The ``AgentName`` Literal is the only place an agent name is declared; every
``IssueBase.source`` and routing dispatch references it so a typo surfaces at
type-check time. ``synthesis_gap_detection`` is reserved for residual issues
emitted by the synthesis pass that the deterministic remediation cannot close.
"""

from __future__ import annotations

from typing import Literal

AgentName = Literal[
    "ingestion",
    "profiler",
    "schema",
    "completeness",
    "duplicate",
    "anomaly",
    "consistency",
    "constraint",
    "synthesis",
    "remediation",
    "code_validator",
    "report",
    "synthesis_gap_detection",
]

ALL_AGENT_NAMES: tuple[AgentName, ...] = (
    "ingestion",
    "profiler",
    "schema",
    "completeness",
    "duplicate",
    "anomaly",
    "consistency",
    "constraint",
    "synthesis",
    "remediation",
    "code_validator",
    "report",
    "synthesis_gap_detection",
)
