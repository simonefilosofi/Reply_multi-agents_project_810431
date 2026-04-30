"""Layer 1 completeness analysis agent. Detects missing values, empty strings,
and common placeholder patterns across all columns. Emits typed Issue
instances into state.completeness_report after Step 9.
"""

from agents_demo._enrichment import enrich_with_llm
from agents_demo.base_agent import SMART, BaseAgent
from state.constants import COMPLETENESS_ISSUE_TYPES
from state.issues import AgentReport, parse_issues
from tools import check_placeholder_values, compute_completeness


class CompletenessAgent(BaseAgent):
    name = "completeness"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a data completeness analyst. You detect missing values, empty "
        "strings, and placeholder patterns (such as 'N/A', 'null', 'unknown') "
        "across all columns. You summarize completeness issues in 2-3 sentences, "
        "focusing on the most impactful missing data and its potential business impact."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        sparse_cols = set(fp.get("sparse_columns", []))

        raw, completeness_by_col, overall = compute_completeness(df, sparse_cols)
        raw.extend(check_placeholder_values(df))

        issues = parse_issues(raw, source=self.name, allowed_types=COMPLETENESS_ISSUE_TYPES)
        issues = enrich_with_llm(self, issues, df, COMPLETENESS_ISSUE_TYPES)
        self.state.completeness_by_column = completeness_by_col
        self.state.overall_completeness = overall
        report: AgentReport = {"issues": issues, "total_issues": len(issues)}
        self.state.completeness_report = report

    def observe(self):
        report = self.state.completeness_report
        self.log(
            "observe",
            f"Found {report['total_issues']} completeness issues. "
            f"Overall dataset completeness: "
            f"{self.state.overall_completeness:.1%}",
        )

    def reply(self):
        self.summarize_issues(
            self.state.completeness_report["issues"],
            "completeness_summary",
            "completeness",
        )
