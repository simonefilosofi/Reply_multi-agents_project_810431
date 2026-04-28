"""Layer 4 report agent. Computes the post-remediation reliability score,
generates the data-quality visualizations (Step 13 adds the
before/after completeness heatmap, the dimension-trajectory line chart,
and the issue-resolution Sankey), compiles the final report dictionary
including ``deliberation_log``, ``gap_issues``, ``validator_outcomes``,
and ``dimension_trajectory``, and produces an LLM-generated executive
narrative. The module also exposes :func:`serialize_report`, the
canonical JSON exporter Streamlit uses to render and download the
final report; it round-trips Pydantic ``Issue`` and
``DeliberationOutcome`` instances via ``model_dump`` instead of the
legacy ``str(obj)`` fallback.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd
from pydantic import BaseModel

from agents_demo.base_agent import SMART, BaseAgent
from state_demo.helpers import missing_mask
from state_demo.scoring import build_rename_aware_resolve, compute_reliability_score
from tools import (
    chart_completeness_heatmap_before_after,
    chart_dimension_trajectory,
    chart_issue_resolution_sankey,
    chart_issues_by_agent,
    chart_reliability_comparison,
    chart_severity_distribution,
)

IMAGES_DIR = "images"


def serialize_report(report: dict[str, Any], indent: int = 2) -> str:
    """Serialize ``state.final_report`` to JSON, handling typed Pydantic members.

    Pydantic ``BaseModel`` instances (typed ``Issue`` discriminated-union
    members, ``DeliberationOutcome`` records) are emitted via
    ``model_dump()``. Pandas timestamps become strings; numpy scalars use
    ``.item()``; DataFrames become record lists. Anything else falls back
    to ``str(obj)`` so the export never raises mid-flight.
    """

    def default_handler(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        if isinstance(obj, (pd.Timestamp, pd.Timedelta)):
            return str(obj)
        if hasattr(obj, "item"):
            return obj.item()
        if isinstance(obj, pd.DataFrame):
            return obj.to_dict(orient="records")
        return str(obj)

    return json.dumps(report, indent=indent, default=default_handler)


def _completeness_by_column(df: pd.DataFrame | None) -> dict[str, float]:
    if df is None or df.empty:
        return {}
    total = len(df)
    return {col: 1 - int(missing_mask(df[col]).sum()) / total for col in df.columns}


class ReportAgent(BaseAgent):
    name = "report"
    model = SMART

    INSTRUCTION = (
        "You are a data quality reporting analyst. You compile comprehensive data "
        "quality reports with reliability scores, visualizations, and executive "
        "narratives. You write 6-8 sentence narratives synthesizing the pipeline "
        "outcome: what was found, what was fixed, what remains, and the reliability "
        "improvement. Be specific with numbers."
    )

    def think(self):
        n_issues = len(self.state.prioritized_issues)
        n_fixes = len(self.state.fix_log)
        n_insights = len(self.state.cross_agent_insights)
        self.log(
            "think",
            f"{self.prompt} | Compiling final report: {n_issues} issues, "
            f"{n_fixes} fix actions, {n_insights} cross-agent insights",
        )

    def act(self):
        os.makedirs(IMAGES_DIR, exist_ok=True)
        dataset_name = os.path.splitext(os.path.basename(self.state.source_path))[0]
        images_dir = os.path.join(IMAGES_DIR, dataset_name)
        os.makedirs(images_dir, exist_ok=True)

        before_score = self.state.reliability_score_before
        _, before_dims = compute_reliability_score(self.state.df_raw, self.state)

        df_cleaned = self.state.df_cleaned
        resolve = build_rename_aware_resolve(self.state, df_cleaned)
        after_score, after_dims = compute_reliability_score(
            df_cleaned,
            self.state,
            resolve=resolve,
        )
        self.state.reliability_score_after = after_score

        completeness_after = _completeness_by_column(df_cleaned)
        viz_paths = [
            chart_severity_distribution(self.state.prioritized_issues, images_dir),
            chart_issues_by_agent(self.state.prioritized_issues, images_dir),
            chart_completeness_heatmap_before_after(
                self.state.completeness_by_column, completeness_after, images_dir
            ),
            chart_reliability_comparison(
                before_dims, after_dims, before_score, after_score, images_dir
            ),
            chart_dimension_trajectory(self.state.dimension_trajectory, images_dir),
            chart_issue_resolution_sankey(
                self.state.fix_log, self.state.prioritized_issues, images_dir
            ),
        ]
        for path in viz_paths:
            if path:
                self.log("act", f"Chart saved: {path}")

        issues = self.state.prioritized_issues
        auto_fixed = sum(
            1 for f in self.state.fix_log if f["action"] in ("auto_fixed", "auto_fixed_by_llm")
        )
        flagged = sum(1 for f in self.state.fix_log if f["action"] == "flagged_for_review")
        recommendations = [
            {
                "column": f["column"],
                "issue_type": f["issue_type"],
                "recommendation": f["description"],
            }
            for f in self.state.fix_log
            if f["action"] == "flagged_for_review"
        ]
        validator_outcomes = [
            f for f in self.state.fix_log if f.get("action") == "auto_fixed_by_llm"
        ] + [
            {
                "column": item["column"],
                "issue_type": item["issue"].get("type", "unknown"),
                "action": "human_review",
                "reason": item["reason"],
                "attempts": item["attempts"],
                "last_error": item.get("last_error", ""),
            }
            for item in self.state.human_review_items
        ]

        self.state.final_report = {
            "title": "Data Quality Report",
            "dataset": {
                "source": self.state.source_path,
                "format": self.state.source_format,
                "rows": len(self.state.df_raw),
                "columns": len(self.state.df_raw.columns),
                "domain": self.state.dataset_fingerprint.get("domain", "unknown"),
            },
            "reliability_score_before": before_score,
            "reliability_score_after": after_score,
            "reliability_dimensions_before": before_dims,
            "reliability_dimensions_after": after_dims,
            "dimension_trajectory": dict(self.state.dimension_trajectory),
            "total_issues_found": len(issues),
            "total_issues_fixed": auto_fixed,
            "total_issues_flagged": flagged,
            "executive_summary": self.state.synthesis_summary,
            "cross_agent_insights": self.state.cross_agent_insights,
            "deliberation_log": [d.model_dump() for d in self.state.deliberation_log],
            "issues_by_severity": {
                "high": sum(1 for i in issues if i["severity"] == "high"),
                "medium": sum(1 for i in issues if i["severity"] == "medium"),
                "low": sum(1 for i in issues if i["severity"] == "low"),
            },
            "remediation_summary": {
                "auto_fixed": auto_fixed,
                "flagged_for_review": flagged,
                "fix_log": self.state.fix_log,
            },
            "gap_issues": list(self.state.gap_issues),
            "validator_outcomes": validator_outcomes,
            "agent_reports": {
                "schema": self.state.schema_report,
                "completeness": self.state.completeness_report,
                "duplicate": self.state.duplicate_report,
                "anomaly": self.state.anomaly_report,
                "consistency": self.state.consistency_report,
            },
            "recommendations": recommendations,
            "visualizations": viz_paths,
            "human_review_items": self.state.human_review_items,
        }

    def observe(self):
        report = self.state.final_report
        required = (
            "title",
            "dataset",
            "reliability_score_before",
            "reliability_score_after",
            "total_issues_found",
            "executive_summary",
            "agent_reports",
            "recommendations",
            "visualizations",
        )
        missing = [k for k in required if k not in report or not report[k]]
        if missing:
            self.log("observe", f"Report gaps detected: {missing}")
        else:
            self.log("observe", "All required report fields populated")
        before = report["reliability_score_before"]
        after = report["reliability_score_after"]
        self.log(
            "observe",
            f"Reliability: {before} -> {after} "
            f"(delta: {after - before:+.1f}). "
            f"Visualizations: {len(report['visualizations'])} charts",
        )

    def reply(self):
        report = self.state.final_report
        before = report["reliability_score_before"]
        after = report["reliability_score_after"]

        user = (
            f"Task: {self.prompt}\n\n"
            f"Dataset: {report['dataset']['source']} "
            f"({report['dataset']['rows']} rows, "
            f"{report['dataset']['columns']} columns, "
            f"domain: {report['dataset']['domain']})\n"
            f"Reliability: {before}/100 -> {after}/100\n"
            f"Issues found: {report['total_issues_found']}\n"
            f"Auto-fixed: {report['total_issues_fixed']}, "
            f"Flagged: {report['total_issues_flagged']}\n"
            f"Severity: {report['issues_by_severity']}\n"
            f"Dimensions before: {report['reliability_dimensions_before']}\n"
            f"Dimensions after: {report['reliability_dimensions_after']}\n"
            f"Recommendations: {len(report['recommendations'])} pending\n\n"
            f"Write the final executive narrative for this data quality report."
        )
        try:
            narrative = self.call_llm(user).strip()
        except Exception as e:
            self.log("error", str(e))
            narrative = (
                f"Data quality analysis complete. Reliability improved from "
                f"{before:.1f} to {after:.1f} out of 100. "
                f"{report['total_issues_fixed']} issues remediated, "
                f"{report['total_issues_flagged']} flagged."
            )
        report["executive_summary"] = narrative
        self.log("reply", narrative)
