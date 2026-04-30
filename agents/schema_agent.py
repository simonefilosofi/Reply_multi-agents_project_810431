"""Layer 1 schema validation agent. Checks column data types against the
fingerprint classification and validates column naming conventions. Emits
typed Issue instances into state.schema_report after Step 9.
"""

from agents_demo._enrichment import enrich_with_llm
from agents_demo.base_agent import SMART, BaseAgent
from state.constants import SCHEMA_ISSUE_TYPES
from state.issues import AgentReport, parse_issues
from tools import check_naming_conventions, check_type_issues


class SchemaAgent(BaseAgent):
    name = "schema"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a data schema validation expert. You verify that columns conform "
        "to their expected data types and naming conventions. You summarize type "
        "mismatches, invalid date values, and naming violations in concise, "
        "actionable 2-3 sentence reports."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint

        raw = check_type_issues(
            df,
            numerical_cols=fp.get("numerical_columns", []),
            date_cols=fp.get("date_columns", []),
        )
        raw += check_naming_conventions(df)

        issues = parse_issues(raw, source=self.name, allowed_types=SCHEMA_ISSUE_TYPES)
        issues = enrich_with_llm(self, issues, df, SCHEMA_ISSUE_TYPES)
        report: AgentReport = {"issues": issues, "total_issues": len(issues)}
        self.state.schema_report = report

    def observe(self):
        issues = self.state.schema_report["issues"]
        type_issues = sum(1 for i in issues if i.type in ("mixed_type", "invalid_dates"))
        naming_issues = sum(1 for i in issues if i.type == "naming_convention")
        self.log(
            "observe",
            f"Found {len(issues)} schema issues: "
            f"{type_issues} type, {naming_issues} naming convention",
        )

    def reply(self):
        self.summarize_issues(
            self.state.schema_report["issues"],
            "schema_summary",
            "schema",
        )
