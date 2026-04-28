"""Layer 1 consistency validation agent. Checks date format consistency,
categorical case consistency, date column ordering, and conditional
completeness between related column pairs. Emits typed Issue instances
into state.consistency_report after Step 9.
"""

from agents_demo._enrichment import enrich_with_llm
from agents_demo.base_agent import SMART, BaseAgent
from state_demo.constants import CONSISTENCY_ISSUE_TYPES
from state_demo.issues import AgentReport, parse_issues
from tools import (
    check_case_consistency,
    check_conditional_completeness,
    check_date_format_consistency,
    check_date_ordering,
    detect_column_mapping_pairs,
)


class ConsistencyAgent(BaseAgent):
    name = "consistency"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a data consistency validator. You check for date format "
        "inconsistencies, categorical case inconsistencies, date ordering "
        "violations, and conditional completeness gaps between related columns. "
        "You summarize consistency issues in 2-3 concise, actionable sentences."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint

        date_cols = [c for c in fp.get("date_columns", []) if c in df.columns]
        cat_cols = [c for c in fp.get("categorical_columns", []) if c in df.columns]

        raw: list[dict] = []
        raw += check_date_format_consistency(df, date_cols)
        raw += check_date_ordering(df, date_cols)
        raw += check_case_consistency(df, cat_cols)
        raw += check_conditional_completeness(df, fp)
        raw += detect_column_mapping_pairs(df)

        issues = parse_issues(raw, source=self.name, allowed_types=CONSISTENCY_ISSUE_TYPES)
        issues = enrich_with_llm(self, issues, df, CONSISTENCY_ISSUE_TYPES)
        report: AgentReport = {"issues": issues, "total_issues": len(issues)}
        self.state.consistency_report = report

    def observe(self):
        issues = self.state.consistency_report["issues"]
        format_issues = sum(1 for i in issues if i.type == "format_inconsistency")
        case_issues = sum(1 for i in issues if i.type == "case_inconsistency")
        order_issues = sum(1 for i in issues if i.type == "date_order")
        cond_issues = sum(1 for i in issues if i.type == "conditional_completeness")
        lookup_issues = sum(1 for i in issues if i.type == "lookup_imputability")
        self.log(
            "observe",
            f"Found {len(issues)} consistency issues: "
            f"{format_issues} format, {case_issues} case, "
            f"{order_issues} date order, {cond_issues} conditional, "
            f"{lookup_issues} lookup-imputability",
        )

    def reply(self):
        self.summarize_issues(
            self.state.consistency_report["issues"],
            "consistency_summary",
            "consistency",
        )
