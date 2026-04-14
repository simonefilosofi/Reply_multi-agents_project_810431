"""Layer 1 constraint validation agent. Enforces domain rules inferred by the
profiler (cross-column equality, format patterns, domain negatives) and runs
deterministic corruption-type and float-precision checks on numeric columns."""

from agents_demo.base_agent import BaseAgent, SMART
from tools import (
    check_column_value_agreement,
    check_domain_negatives,
    check_float_precision,
    check_format_pattern,
    check_fractional_integers,
    check_numeric_corruption_types,
)

_CONSTRAINT_HANDLERS = {
    "must_equal_column": lambda df, c: check_column_value_agreement(
        df, c["column"], c["other_column"]
    ),
    "no_negatives": lambda df, c: check_domain_negatives(df, c["column"]),
    "format_pattern": lambda df, c: check_format_pattern(
        df, c["column"], c["pattern"], c.get("description", "")
    ),
}


class ConstraintAgent(BaseAgent):
    name = "constraint"
    model = SMART

    INSTRUCTION = (
        "You are a domain constraint validator. You enforce structural and "
        "business rules inferred from the dataset profile: cross-column value "
        "agreement, domain-specific format patterns, and impossible value ranges. "
        "You also characterize numeric corruption subtypes (currency symbols, "
        "comma decimals, ND placeholders) and float precision noise. "
        "Summarize findings in 2-3 concise, actionable sentences."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        for constraint in fp.get("column_constraints", []):
            ctype = constraint.get("type", "")
            handler = _CONSTRAINT_HANDLERS.get(ctype)
            if handler is None:
                self.log("act", f"Unknown constraint type '{ctype}' — skipped")
                continue
            try:
                new_issues = handler(df, constraint)
                issues.extend(new_issues)
                if new_issues:
                    self.log(
                        "act",
                        f"Constraint '{ctype}' on '{constraint.get('column')}': "
                        f"{len(new_issues)} issue(s) found",
                    )
            except Exception as e:
                self.log("act", f"Constraint check failed ({ctype}): {e}")

        schema_issues = self.state.schema_report.get("issues", [])
        mixed_cols = [i["column"] for i in schema_issues if i["type"] == "mixed_type"]
        for col in mixed_cols:
            corruption_issues = check_numeric_corruption_types(df, col)
            issues.extend(corruption_issues)
            if corruption_issues:
                self.log(
                    "act",
                    f"Numeric corruption subtypes in '{col}': "
                    + ", ".join(i["type"] for i in corruption_issues),
                )

        precision_issues = check_float_precision(df, fp.get("numerical_columns", []))
        issues.extend(precision_issues)
        if precision_issues:
            self.log(
                "act",
                f"Float precision noise detected in "
                f"{len(precision_issues)} column(s)",
            )

        fractional_issues = check_fractional_integers(
            df, fp.get("numerical_columns", [])
        )
        issues.extend(fractional_issues)
        if fractional_issues:
            self.log(
                "act",
                f"Fractional-integer corruption detected in "
                f"{len(fractional_issues)} column(s): "
                + ", ".join(i["column"] for i in fractional_issues),
            )

        self.state.constraint_report = {
            "issues": issues,
            "total_issues": len(issues),
        }

    def observe(self):
        issues = self.state.constraint_report["issues"]
        type_counts: dict = {}
        for i in issues:
            type_counts[i["type"]] = type_counts.get(i["type"], 0) + 1
        summary = ", ".join(f"{k}: {v}" for k, v in type_counts.items()) or "none"
        self.log(
            "observe",
            f"Found {len(issues)} constraint issues — {summary}",
        )

    def reply(self):
        self.summarize_issues(
            self.state.constraint_report["issues"],
            "constraint_summary",
            "constraint",
        )
