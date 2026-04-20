"""Layer 1 completeness analysis agent. Detects missing values, empty strings,
and common placeholder patterns across all columns."""

from agents_demo.base_agent import BaseAgent, SMART
from tools import compute_completeness, check_placeholder_values


class CompletenessAgent(BaseAgent):
    name = "completeness"
    model = SMART

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

        issues, completeness_by_col, overall = compute_completeness(df, sparse_cols)

        placeholder_issues = check_placeholder_values(df)
        issues.extend(placeholder_issues)

        self.state.completeness_by_column = completeness_by_col
        self.state.overall_completeness = overall
        self.state.completeness_report = {
            "issues": issues,
            "total_issues": len(issues),
        }

    def observe(self):
        report = self.state.completeness_report
        self.log("observe",
                 f"Found {report['total_issues']} completeness issues. "
                 f"Overall dataset completeness: "
                 f"{self.state.overall_completeness:.1%}")

    def reply(self):
        self.summarize_issues(
            self.state.completeness_report["issues"],
            "completeness_summary", "completeness",
        )
