"""Pipeline state dataclass holding all intermediate and final results
produced by agents across all layers of the data quality pipeline.

After Step 9 the per-detector report fields are typed as ``AgentReport``
TypedDicts whose ``issues`` member is a ``list[Issue]`` (the discriminated
union from ``state_demo.issues``). Detector agents write typed instances and,
from Step 10 onward, the synthesis supervisor consumes them as typed Issues
and records each deliberation pass as a :class:`DeliberationOutcome` in
``deliberation_log``. The remediation and report agents continue to read
issues through the dict-style accessors exposed by ``IssueBase`` until those
layers are migrated in Steps 11-13.
"""

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from state_demo.deliberation import DeliberationOutcome
from state_demo.issues import AgentReport, Issue


def _empty_report() -> AgentReport:
    return {"issues": [], "total_issues": 0}


@dataclass
class PipelineState:
    source_path: str = ""
    source_format: str = ""

    df_raw: pd.DataFrame = field(default_factory=pd.DataFrame)
    ingestion_meta: dict[str, Any] = field(default_factory=dict)
    dataset_fingerprint: dict[str, Any] = field(default_factory=dict)

    agent_log: list[dict[str, Any]] = field(default_factory=list)
    cross_agent_insights: list[dict[str, Any]] = field(default_factory=list)

    completeness_by_column: dict[str, float] = field(default_factory=dict)
    overall_completeness: float = 0.0

    schema_report: AgentReport = field(default_factory=_empty_report)
    completeness_report: AgentReport = field(default_factory=_empty_report)
    duplicate_report: AgentReport = field(default_factory=_empty_report)
    anomaly_report: AgentReport = field(default_factory=_empty_report)
    consistency_report: AgentReport = field(default_factory=_empty_report)
    constraint_report: AgentReport = field(default_factory=_empty_report)

    schema_summary: str = ""
    completeness_summary: str = ""
    duplicate_summary: str = ""
    anomaly_summary: str = ""
    consistency_summary: str = ""
    constraint_summary: str = ""

    prioritized_issues: list[Issue] = field(default_factory=list)
    deliberation_log: list[DeliberationOutcome] = field(default_factory=list)
    synthesis_summary: str = ""

    remediation_plan: list[dict[str, Any]] = field(default_factory=list)
    fix_log: list[dict[str, Any]] = field(default_factory=list)
    df_cleaned: pd.DataFrame | None = None

    human_review_items: list[dict[str, Any]] = field(default_factory=list)

    reliability_score_before: float = 0.0
    reliability_score_after: float = 0.0
    final_report: dict[str, Any] = field(default_factory=dict)
