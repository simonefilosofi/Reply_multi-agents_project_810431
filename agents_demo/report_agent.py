"""Layer 4 report agent. Computes the post-remediation reliability score,
generates four data quality visualizations, compiles the final report
dictionary, and produces an LLM-generated executive narrative."""

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from agents.base_agent import BaseAgent, SMART
from state.scoring import compute_reliability_score

IMAGES_DIR = "images"


class ReportAgent(BaseAgent):
    name = "report"
    model = SMART

    def think(self):
        n_issues = len(self.state.prioritized_issues)
        n_fixes = len(self.state.fix_log)
        n_insights = len(self.state.cross_agent_insights)
        self.log("think",
                 f"Compiling final report: {n_issues} issues, "
                 f"{n_fixes} fix actions, {n_insights} cross-agent insights")

    def act(self):
        os.makedirs(IMAGES_DIR, exist_ok=True)
        dataset_name = os.path.splitext(
            os.path.basename(self.state.source_path)
        )[0]
        self._images_dir = os.path.join(IMAGES_DIR, dataset_name)
        os.makedirs(self._images_dir, exist_ok=True)
        self._rename_map = self._build_rename_map()

        before_score = self.state.reliability_score_before
        _, before_dims = compute_reliability_score(
            self.state.df_raw, self.state,
        )
        after_score, after_dims = compute_reliability_score(
            self.state.df_cleaned, self.state,
            resolve=self._resolve_col_fn(),
        )
        self.state.reliability_score_after = after_score

        viz_paths = self._generate_visualizations(before_dims, after_dims)

        issues = self.state.prioritized_issues
        auto_fixed = sum(
            1 for f in self.state.fix_log
            if f["action"] == "auto_fixed"
        )
        flagged = sum(
            1 for f in self.state.fix_log
            if f["action"] == "flagged_for_review"
        )
        recommendations = [
            {
                "column": f["column"],
                "issue_type": f["issue_type"],
                "recommendation": f["description"],
            }
            for f in self.state.fix_log
            if f["action"] == "flagged_for_review"
        ]

        self.state.final_report = {
            "title": "Data Quality Report",
            "dataset": {
                "source": self.state.source_path,
                "format": self.state.source_format,
                "rows": len(self.state.df_raw),
                "columns": len(self.state.df_raw.columns),
                "domain": self.state.dataset_fingerprint.get(
                    "domain", "unknown",
                ),
            },
            "reliability_score_before": before_score,
            "reliability_score_after": after_score,
            "reliability_dimensions_before": before_dims,
            "reliability_dimensions_after": after_dims,
            "total_issues_found": len(issues),
            "total_issues_fixed": auto_fixed,
            "total_issues_flagged": flagged,
            "executive_summary": self.state.synthesis_summary,
            "cross_agent_insights": self.state.cross_agent_insights,
            "issues_by_severity": {
                "high": sum(
                    1 for i in issues if i["severity"] == "high"
                ),
                "medium": sum(
                    1 for i in issues if i["severity"] == "medium"
                ),
                "low": sum(
                    1 for i in issues if i["severity"] == "low"
                ),
            },
            "remediation_summary": {
                "auto_fixed": auto_fixed,
                "flagged_for_review": flagged,
                "fix_log": self.state.fix_log,
            },
            "agent_reports": {
                "schema": self.state.schema_report,
                "completeness": self.state.completeness_report,
                "duplicate": self.state.duplicate_report,
                "anomaly": self.state.anomaly_report,
                "consistency": self.state.consistency_report,
            },
            "recommendations": recommendations,
            "visualizations": viz_paths,
        }

    def observe(self):
        report = self.state.final_report
        missing_keys = [
            k for k in (
                "title", "dataset", "reliability_score_before",
                "reliability_score_after", "total_issues_found",
                "executive_summary", "agent_reports",
                "recommendations", "visualizations",
            )
            if k not in report or not report[k]
        ]
        if missing_keys:
            self.log("observe",
                     f"Report gaps detected: {missing_keys}")
        else:
            self.log("observe", "All required report fields populated")

        before = report["reliability_score_before"]
        after = report["reliability_score_after"]
        delta = after - before
        self.log("observe",
                 f"Reliability: {before} -> {after} "
                 f"(delta: {delta:+.1f}). "
                 f"Visualizations: {len(report['visualizations'])} charts")

    def reply(self):
        report = self.state.final_report
        before = report["reliability_score_before"]
        after = report["reliability_score_after"]
        total_fixed = report["total_issues_fixed"]
        total_flagged = report["total_issues_flagged"]

        system = (
            "You are a data quality analyst writing the final executive "
            "narrative for a comprehensive data quality report. Write "
            "6-8 sentences synthesizing the pipeline outcome: what was "
            "found, what was fixed, what remains, and the reliability "
            "improvement. Be specific with numbers."
        )
        user = (
            f"Dataset: {report['dataset']['source']} "
            f"({report['dataset']['rows']} rows, "
            f"{report['dataset']['columns']} columns, "
            f"domain: {report['dataset']['domain']})\n"
            f"Reliability: {before}/100 -> {after}/100\n"
            f"Issues found: {report['total_issues_found']}\n"
            f"Auto-fixed: {total_fixed}, Flagged: {total_flagged}\n"
            f"Severity: {report['issues_by_severity']}\n"
            f"Dimensions before: {report['reliability_dimensions_before']}\n"
            f"Dimensions after: {report['reliability_dimensions_after']}\n"
            f"Recommendations: {len(report['recommendations'])} pending"
        )

        try:
            narrative = self.call_llm(system, user).strip()
        except Exception as e:
            self.log("error", str(e))
            narrative = (
                f"Data quality analysis complete. Reliability improved "
                f"from {before:.1f} to {after:.1f} out of 100. "
                f"{total_fixed} issues remediated, "
                f"{total_flagged} flagged."
            )

        self.state.final_report["executive_summary"] = narrative
        self.log("reply", narrative)

    def _build_rename_map(self):
        return {
            f["metadata"]["old"]: f["metadata"]["new"]
            for f in self.state.fix_log
            if f["issue_type"] == "naming_convention"
            and f["action"] == "auto_fixed"
            and "metadata" in f
        }

    def _resolve_col(self, col, df):
        if col in df.columns:
            return col
        renamed = self._rename_map.get(col)
        if renamed and renamed in df.columns:
            return renamed
        return None

    def _resolve_col_fn(self):
        df = self.state.df_cleaned

        def resolve(col):
            return self._resolve_col(col, df)

        return resolve

    def _generate_visualizations(self, before_dims, after_dims):
        paths = []
        plt.rcParams.update({
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "font.size": 10,
        })

        paths.append(self._chart_severity_distribution())
        paths.append(self._chart_issues_by_agent())
        paths.append(self._chart_completeness_heatmap())
        paths.append(
            self._chart_reliability_comparison(before_dims, after_dims)
        )
        return paths

    def _chart_severity_distribution(self):
        issues = self.state.prioritized_issues
        severities = ["high", "medium", "low"]
        counts = [
            sum(1 for i in issues if i["severity"] == s)
            for s in severities
        ]
        colors = ["#d9534f", "#f0ad4e", "#5bc0de"]

        fig, ax = plt.subplots(figsize=(6, 4))
        bars = ax.bar(
            [s.capitalize() for s in severities], counts, color=colors,
        )
        for bar, count in zip(bars, counts):
            if count > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                        str(count), ha="center", va="bottom", fontweight="bold")
        ax.set_ylabel("Issue Count")
        ax.set_title("Issue Severity Distribution")

        path = os.path.join(self._images_dir, "issue_severity_distribution.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        self.log("act", f"Chart saved: {path}")
        return path

    def _chart_issues_by_agent(self):
        issues = self.state.prioritized_issues
        agents = ["schema", "completeness", "duplicate",
                  "anomaly", "consistency"]
        severities = ["high", "medium", "low"]
        colors = ["#d9534f", "#f0ad4e", "#5bc0de"]

        data = {}
        for sev in severities:
            data[sev] = [
                sum(1 for i in issues
                    if i.get("source") == agent and i["severity"] == sev)
                for agent in agents
            ]

        x = np.arange(len(agents))
        width = 0.25

        fig, ax = plt.subplots(figsize=(10, 5))
        for idx, sev in enumerate(severities):
            ax.bar(x + idx * width, data[sev], width,
                   label=sev.capitalize(), color=colors[idx])

        ax.set_xticks(x + width)
        ax.set_xticklabels(
            [a.capitalize() + "Agent" for a in agents], rotation=15,
        )
        ax.set_ylabel("Issue Count")
        ax.set_title("Issues by Agent and Severity")
        ax.legend()

        path = os.path.join(self._images_dir, "issues_by_agent.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        self.log("act", f"Chart saved: {path}")
        return path

    def _chart_completeness_heatmap(self):
        comp = self.state.completeness_by_column
        if not comp:
            return ""

        cols = list(comp.keys())
        values = [comp[c] for c in cols]
        display_names = [
            c[:18] + "..." if len(c) > 20 else c for c in cols
        ]

        fig, ax = plt.subplots(figsize=(max(8, len(cols) * 0.6), 2.5))
        data = np.array([values])
        im = ax.imshow(
            data, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1,
        )

        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(display_names, rotation=45, ha="right",
                           fontsize=8)
        ax.set_yticks([])
        plt.colorbar(im, ax=ax, label="Completeness Rate", shrink=0.8)
        ax.set_title("Completeness Rate by Column (Before Remediation)")

        for idx, val in enumerate(values):
            color = "white" if val < 0.5 else "black"
            ax.text(idx, 0, f"{val:.0%}", ha="center", va="center",
                    fontsize=7, color=color)

        path = os.path.join(self._images_dir, "completeness_heatmap.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        self.log("act", f"Chart saved: {path}")
        return path

    def _chart_reliability_comparison(self, before_dims, after_dims):
        all_dim_keys = [
            "schema_conformity", "completeness", "uniqueness",
            "consistency", "anomaly_freedom",
        ]
        labels = [
            "Schema\nConformity", "Completeness", "Uniqueness",
            "Consistency", "Anomaly\nFreedom",
        ]

        present_keys = [
            k for k in all_dim_keys
            if k in before_dims or k in after_dims
        ]
        present_labels = [
            labels[all_dim_keys.index(k)] for k in present_keys
        ]

        before_vals = [before_dims.get(k, 0) for k in present_keys]
        after_vals = [after_dims.get(k, 0) for k in present_keys]

        x = np.arange(len(present_keys))
        width = 0.35

        fig, ax = plt.subplots(figsize=(10, 5))
        bars_b = ax.bar(
            x - width / 2, before_vals, width,
            label="Before Remediation", color="#6c757d",
        )
        bars_a = ax.bar(
            x + width / 2, after_vals, width,
            label="After Remediation", color="#28a745",
        )

        for bar in list(bars_b) + list(bars_a):
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h,
                    f"{h:.2f}", ha="center", va="bottom", fontsize=8)

        ax.set_xticks(x)
        ax.set_xticklabels(present_labels)
        ax.set_ylabel("Score (0-1)")
        ax.set_ylim(0, 1.15)
        ax.set_title(
            f"Reliability Dimensions: "
            f"{self.state.reliability_score_before}/100 -> "
            f"{self.state.reliability_score_after}/100"
        )
        ax.legend()

        path = os.path.join(self._images_dir, "reliability_before_after.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        self.log("act", f"Chart saved: {path}")
        return path
