from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class PipelineState:
    # --- Input ---
    source_path: str = ""
    source_format: str = ""

    # --- Layer 0 ---
    df_raw: pd.DataFrame = field(default_factory=pd.DataFrame)
    ingestion_meta: dict = field(default_factory=dict)
    dataset_fingerprint: dict = field(default_factory=dict)

    # --- Layer 1 (one dict per agent) ---
    schema_report: dict = field(default_factory=dict)
    completeness_report: dict = field(default_factory=dict)
    duplicate_report: dict = field(default_factory=dict)
    anomaly_report: dict = field(default_factory=dict)

    # Compact summaries for SynthesisAgent
    schema_summary: str = ""
    completeness_summary: str = ""
    duplicate_summary: str = ""
    anomaly_summary: str = ""

    # --- Layer 2 ---
    prioritized_issues: list = field(default_factory=list)

    # --- Layer 3 ---
    remediation_plan: list = field(default_factory=list)
    fix_log: list = field(default_factory=list)
    df_cleaned: Optional[pd.DataFrame] = None

    # --- Layer 4 ---
    reliability_score_before: float = 0.0
    reliability_score_after: float = 0.0
    final_report: dict = field(default_factory=dict)
