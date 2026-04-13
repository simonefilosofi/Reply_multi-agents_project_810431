"""Layer 1 completeness analysis agent. Detects missing values, empty strings,
and common placeholder patterns across all columns. Reports per-column and
overall completeness rates and flags sparse columns for potential removal."""

from agents.base_agent import BaseAgent, SMART
from state.helpers import missing_mask


class CompletenessAgent(BaseAgent):
    name = "completeness"
    model = SMART

    def think(self):
        self.log("think",
                 "Checking all columns for missing values, empty strings, "
                 "and common placeholder patterns")

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []
        total_missing_all = 0

        for col in df.columns:
            total = len(df)
            col_missing = missing_mask(df[col])
            missing_count = int(col_missing.sum())

            rate = missing_count / total if total > 0 else 0
            self.state.completeness_by_column[col] = 1 - rate
            total_missing_all += missing_count

            if rate > 0.50:
                severity = "high"
            elif rate > 0.20:
                severity = "medium"
            elif rate > 0.05:
                severity = "low"
            else:
                continue

            issues.append({
                "column": col,
                "type": "missing_values",
                "detail": (f"{rate:.0%} of values are missing, empty, "
                           f"or placeholder ({missing_count}/{total})"),
                "severity": severity,
            })

        sparse_cols = set(fp.get("sparse_columns", []))
        for col in sparse_cols:
            if col not in df.columns:
                continue
            col_completeness = self.state.completeness_by_column.get(
                col, 1.0,
            )
            empty_pct = 1 - col_completeness
            issues.append({
                "column": col,
                "type": "sparse_column",
                "detail": (f"Column is {empty_pct:.0%} empty "
                           "\u2014 candidate for removal"),
                "severity": "medium",
            })

        total_cells = len(df) * len(df.columns)
        self.state.overall_completeness = (
            1 - (total_missing_all / total_cells) if total_cells > 0
            else 1.0
        )

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
