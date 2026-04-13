"""Pipeline state dataclass holding all intermediate and final results
produced by agents across all layers of the data quality pipeline."""

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd


@dataclass
class PipelineState:
    source_path: str = ""
    source_format: str = ""

    df_raw: pd.DataFrame = field(default_factory=pd.DataFrame)
    ingestion_meta: dict = field(default_factory=dict)
    dataset_fingerprint: dict = field(default_factory=dict)

    agent_log: list = field(default_factory=list)
    cross_agent_insights: list = field(default_factory=list)

    completeness_by_column: dict = field(default_factory=dict)
    overall_completeness: float = 0.0

    schema_report: dict = field(default_factory=dict)
    completeness_report: dict = field(default_factory=dict)
    duplicate_report: dict = field(default_factory=dict)
    anomaly_report: dict = field(default_factory=dict)
    consistency_report: dict = field(default_factory=dict)

    schema_summary: str = ""
    completeness_summary: str = ""
    duplicate_summary: str = ""
    anomaly_summary: str = ""
    consistency_summary: str = ""

    prioritized_issues: list = field(default_factory=list)
    synthesis_summary: str = ""

    remediation_plan: list = field(default_factory=list)
    fix_log: list = field(default_factory=list)
    df_cleaned: Optional[pd.DataFrame] = None

    reliability_score_before: float = 0.0
    reliability_score_after: float = 0.0
    final_report: dict = field(default_factory=dict)
