"""Layer 1 anomaly detection agent. Detects statistical outliers in numerical
columns using the 3-sigma rule and rare categories in categorical columns."""

from agents_demo.base_agent import BaseAgent, SMART
from tools import detect_outliers, detect_rare_categories


class AnomalyAgent(BaseAgent):
    name = "anomaly"
    model = SMART

    INSTRUCTION = (
        "You are a statistical anomaly detection specialist. You detect numerical "
        "outliers using the 3-sigma rule and identify rare categories appearing in "
        "less than 1% of rows. You summarize anomaly findings in 2-3 sentences, "
        "distinguishing between isolated outliers and systematic distributional issues."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint

        issues = []
        issues += detect_outliers(df, fp.get("numerical_columns", []))
        issues += detect_rare_categories(df, fp.get("categorical_columns", []))

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
