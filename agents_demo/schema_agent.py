"""Layer 1 schema validation agent. Checks column data types against the
fingerprint classification, detects type mismatches, and validates column
naming conventions against snake_case and reserved word rules."""

import re

import pandas as pd

from agents.base_agent import BaseAgent, SMART
from state.helpers import non_empty_values

RESERVED_WORDS = {
    "class", "def", "return", "import", "from", "lambda", "global",
    "none", "true", "false", "and", "or", "not", "in", "is",
    "if", "else", "for", "while", "try", "except", "with", "as",
    "pass", "break", "continue", "yield",
    "select", "where", "join", "insert", "update", "delete", "drop",
    "table", "index", "group", "order", "having", "union", "create",
    "alter",
    "values", "columns", "dtypes", "shape", "name", "count",
}


class SchemaAgent(BaseAgent):
    name = "schema"
    model = SMART

    def think(self):
        self.log("think",
                 "Validating column data types and naming conventions")

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        for col in fp.get("numerical_columns", []):
            if col not in df.columns:
                continue
            non_empty = non_empty_values(df[col])
            if len(non_empty) == 0:
                continue
            non_numeric_count = int(
                pd.to_numeric(non_empty, errors="coerce").isna().sum()
            )
            if non_numeric_count > 0:
                non_numeric_pct = non_numeric_count / len(non_empty)
                if non_numeric_pct > 0.20:
                    severity = "high"
                elif non_numeric_pct > 0.05:
                    severity = "medium"
                else:
                    severity = "low"
                issues.append({
                    "column": col,
                    "type": "mixed_type",
                    "detail": (
                        f"Expected numeric but {non_numeric_count} "
                        f"values ({non_numeric_pct:.0%}) cannot parse "
                        f"as numbers"),
                    "severity": severity,
                })

        for col in fp.get("date_columns", []):
            if col not in df.columns:
                continue
            non_empty = non_empty_values(df[col])
            bad_frac = pd.to_datetime(
                non_empty, errors="coerce", dayfirst=True,
            ).isna().mean()
            if bad_frac > 0.10:
                issues.append({
                    "column": col,
                    "type": "invalid_dates",
                    "detail": (f"{bad_frac:.0%} values cannot be parsed "
                               f"as dates"),
                    "severity": "medium",
                })

        for col in df.columns:
            violations = []

            if col != col.strip():
                violations.append("leading/trailing whitespace")

            if " " in col.strip():
                violations.append("contains spaces")

            if re.search(r"[^a-zA-Z0-9_ ]", col):
                violations.append("contains special characters")

            if col != col.lower():
                violations.append("not snake_case (contains uppercase)")

            if col.strip().lower() in RESERVED_WORDS:
                violations.append(
                    f"'{col.strip().lower()}' is a reserved word"
                )

            if violations:
                issues.append({
                    "column": col,
                    "type": "naming_convention",
                    "detail": "; ".join(violations),
                    "severity": "low",
                })

        self.state.schema_report = {
            "issues": issues,
            "total_issues": len(issues),
        }

    def observe(self):
        report = self.state.schema_report
        issues = report["issues"]
        type_issues = sum(
            1 for i in issues
            if i["type"] in ("mixed_type", "invalid_dates")
        )
        naming_issues = sum(
            1 for i in issues if i["type"] == "naming_convention"
        )
        self.log("observe",
                 f"Found {report['total_issues']} schema issues: "
                 f"{type_issues} type, {naming_issues} naming convention")

    def reply(self):
        self.summarize_issues(
            self.state.schema_report["issues"],
            "schema_summary", "schema",
        )
