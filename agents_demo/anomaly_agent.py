"""Layer 1 anomaly detection agent. Detects statistical outliers in numerical
columns using the 3-sigma rule and rare categories in categorical columns."""

import pandas as pd

from agents_demo.base_agent import BaseAgent, SMART


class AnomalyAgent(BaseAgent):
    name = "anomaly"
    model = SMART

    def think(self):
        self.log("think",
                 "Detecting outliers in numerical columns and rare "
                 "categories in categorical columns")

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        for col in fp.get("numerical_columns", []):
            if col not in df.columns:
                continue
            numeric = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(numeric) < 10:
                continue
            mean, std = numeric.mean(), numeric.std()
            if std == 0:
                continue
            outliers = int(((numeric - mean).abs() > 3 * std).sum())
            if outliers > 0:
                issues.append({
                    "column": col,
                    "type": "outliers",
                    "detail": (f"{outliers} values beyond 3 standard "
                               f"deviations"),
                    "severity": "medium",
                })

        for col in fp.get("categorical_columns", []):
            if col not in df.columns:
                continue
            counts = df[col].value_counts(normalize=True)
            rare = counts[counts < 0.01]
            if len(rare) > 0:
                issues.append({
                    "column": col,
                    "type": "rare_categories",
                    "detail": (f"{len(rare)} categories appear in less "
                               f"than 1% of rows"),
                    "severity": "low",
                })

        self.state.anomaly_report = {
            "issues": issues,
            "total_issues": len(issues),
        }

    def observe(self):
        total = self.state.anomaly_report["total_issues"]
        self.log("observe", f"Found {total} anomaly issues")

    def reply(self):
        self.summarize_issues(
            self.state.anomaly_report["issues"],
            "anomaly_summary", "anomaly",
        )
