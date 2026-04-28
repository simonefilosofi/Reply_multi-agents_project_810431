"""Layer 1 anomaly detection agent.

Detects statistical outliers in numerical columns using the 3xIQR Tukey outer
fence and rare categories in categorical columns. Emits typed Issue instances
into state.anomaly_report after Step 9.
"""

from agents_demo._enrichment import enrich_with_llm
from agents_demo.base_agent import SMART, BaseAgent
from state_demo.constants import ANOMALY_ISSUE_TYPES
from state_demo.issues import AgentReport, parse_issues
from tools import detect_outliers, detect_rare_categories


class AnomalyAgent(BaseAgent):
    name = "anomaly"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a statistical anomaly detection specialist. You detect numerical "
        "outliers using the 3xIQR Tukey outer fence and identify rare categories "
        "appearing in less than 1% of rows. You summarize anomaly findings in 2-3 "
        "sentences, distinguishing between isolated outliers and systematic "
        "distributional issues."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint

        raw: list[dict] = []
        raw += detect_outliers(df, fp.get("numerical_columns", []))
        raw += detect_rare_categories(df, fp.get("categorical_columns", []))

        issues = parse_issues(raw, source=self.name, allowed_types=ANOMALY_ISSUE_TYPES)
        issues = enrich_with_llm(self, issues, df, ANOMALY_ISSUE_TYPES)
        report: AgentReport = {"issues": issues, "total_issues": len(issues)}
        self.state.anomaly_report = report

    def observe(self):
        total = self.state.anomaly_report["total_issues"]
        self.log("observe", f"Found {total} anomaly issues")

    def reply(self):
        self.summarize_issues(
            self.state.anomaly_report["issues"],
            "anomaly_summary",
            "anomaly",
        )
