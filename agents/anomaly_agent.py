# AnomalyAgent — Layer 1
# Detects anomalous values within columns:
# 1. Numerical outliers: values beyond 3 standard deviations from the column mean.
# 2. Rare categories: categorical values that appear in less than 1% of rows,
#    which may indicate typos, legacy codes, or data entry errors.
# Detection is pure code; the LLM is called only to write a human-readable summary.

import pandas as pd
from agents.base_agent import BaseAgent, SMART


class AnomalyAgent(BaseAgent):
    name = "anomaly"
    model = SMART

    def run(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        # Outliers in numerical columns (beyond 3 standard deviations)
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
                    "detail": f"{outliers} values beyond 3 standard deviations",
                    "severity": "medium",
                })

        # Rare categories in categorical columns (< 1% frequency)
        for col in fp.get("categorical_columns", []):
            if col not in df.columns:
                continue
            counts = df[col].value_counts(normalize=True)
            rare = counts[counts < 0.01]
            if len(rare) > 0:
                issues.append({
                    "column": col,
                    "type": "rare_categories",
                    "detail": f"{len(rare)} categories appear in less than 1% of rows",
                    "severity": "low",
                })

        self.state.anomaly_report = {"issues": issues, "total_issues": len(issues)}

        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}" for i in issues
        ) or "No anomalies found."

        try:
            self.state.anomaly_summary = self.call_llm(
                "You are a data quality analyst. Summarize these anomaly issues in 2-3 sentences.",
                f"Anomaly issues:\n{issues_text}"
            ).strip()
        except Exception:
            self.state.anomaly_summary = f"{len(issues)} anomaly issues found."

        print(f"[Anomaly] {len(issues)} issues found.")
