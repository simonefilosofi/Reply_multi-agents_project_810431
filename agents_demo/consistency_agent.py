"""Layer 1 consistency validation agent. Checks date format consistency,
categorical case consistency, date column ordering, and conditional
completeness between related column pairs."""

from itertools import combinations

import pandas as pd

from agents_demo.base_agent import BaseAgent, SMART
from state_demo.constants import DATE_PATTERNS
from state_demo.helpers import non_empty_values


class ConsistencyAgent(BaseAgent):
    name = "consistency"
    model = SMART

    def think(self):
        self.log("think",
                 "Checking date format consistency, categorical case "
                 "consistency, date ordering, and conditional completeness")

    def act(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        date_cols = [c for c in fp.get("date_columns", [])
                     if c in df.columns]

        issues.extend(self._check_date_format_consistency(df, date_cols))

        issues.extend(self._check_date_ordering(df, date_cols))

        cat_cols = [c for c in fp.get("categorical_columns", [])
                    if c in df.columns]
        issues.extend(self._check_case_consistency(df, cat_cols))

        issues.extend(
            self._check_conditional_completeness(df, fp)
        )

        self.state.consistency_report = {
            "issues": issues,
            "total_issues": len(issues),
        }

    def _check_date_format_consistency(self, df, date_cols):
        issues = []
        for col in date_cols:
            non_empty = non_empty_values(df[col])
            if len(non_empty) < 10:
                continue

            values = non_empty.astype(str).str.strip()
            pattern_counts = {}

            for val in values:
                for label, regex in DATE_PATTERNS:
                    if regex.match(val):
                        pattern_counts[label] = (
                            pattern_counts.get(label, 0) + 1
                        )
                        break

            total_matched = sum(pattern_counts.values())
            if total_matched == 0:
                continue

            significant_patterns = [
                label for label, count in pattern_counts.items()
                if count / total_matched > 0.05
            ]

            if len(significant_patterns) >= 2:
                format_detail = ", ".join(
                    f"{label} ({pattern_counts[label]})"
                    for label in significant_patterns
                )
                issues.append({
                    "column": col,
                    "type": "format_inconsistency",
                    "detail": (f"{len(significant_patterns)} date formats "
                               f"detected: {format_detail}"),
                    "severity": "medium",
                })

        return issues

    def _check_date_ordering(self, df, date_cols):
        issues = []
        for col_a, col_b in combinations(date_cols, 2):
            parsed_a = pd.to_datetime(
                df[col_a], errors="coerce", dayfirst=True,
            )
            parsed_b = pd.to_datetime(
                df[col_b], errors="coerce", dayfirst=True,
            )
            both_valid = parsed_a.notna() & parsed_b.notna()
            if both_valid.sum() < 10:
                continue
            violations = int(
                (parsed_a[both_valid] > parsed_b[both_valid]).sum()
            )
            if violations > 0:
                issues.append({
                    "column": f"{col_a} / {col_b}",
                    "type": "date_order",
                    "detail": (f"{violations} rows where '{col_a}' is "
                               f"later than '{col_b}'"),
                    "severity": ("high"
                                 if violations / both_valid.sum() > 0.05
                                 else "medium"),
                })

        return issues

    def _check_case_consistency(self, df, cat_cols):
        issues = []
        for col in cat_cols:
            non_empty = non_empty_values(df[col])
            if len(non_empty) < 10:
                continue

            stripped = non_empty.astype(str).str.strip()
            raw_unique = stripped.nunique()
            lower_unique = stripped.str.lower().nunique()

            if raw_unique <= lower_unique:
                continue

            difference = raw_unique - lower_unique
            if difference > 3 and difference / raw_unique > 0.05:
                issues.append({
                    "column": col,
                    "type": "case_inconsistency",
                    "detail": (f"{difference} values differ only by case "
                               f"({raw_unique} unique raw vs "
                               f"{lower_unique} unique lowercase)"),
                    "severity": "low",
                })

        return issues

    def _check_conditional_completeness(self, df, fp):
        issues = []
        id_cols_set = set(fp.get("id_columns", []))
        col_list = list(df.columns)

        related_pairs = [
            (col_a, col_b)
            for col_a, col_b in combinations(col_list, 2)
            if col_a.split("_")[0].lower() == col_b.split("_")[0].lower()
            and len(col_a.split("_")[0]) >= 4
            and col_a not in id_cols_set
            and col_b not in id_cols_set
        ]

        for col_a, col_b in related_pairs:
            filled_a = (df[col_a].notna()
                        & (df[col_a].astype(str).str.strip() != ""))
            filled_b = (df[col_b].notna()
                        & (df[col_b].astype(str).str.strip() != ""))
            if filled_a.sum() < 10:
                continue
            fill_rate = filled_b[filled_a].mean()
            if 0.90 <= fill_rate < 1.0:
                missing_when_a = int((filled_a & ~filled_b).sum())
                issues.append({
                    "column": f"{col_a} / {col_b}",
                    "type": "conditional_completeness",
                    "detail": (f"{missing_when_a} rows have '{col_a}' "
                               f"filled but '{col_b}' empty"),
                    "severity": "low",
                })

        return issues

    def observe(self):
        report = self.state.consistency_report
        issues = report["issues"]
        format_issues = sum(
            1 for i in issues if i["type"] == "format_inconsistency"
        )
        case_issues = sum(
            1 for i in issues if i["type"] == "case_inconsistency"
        )
        order_issues = sum(
            1 for i in issues if i["type"] == "date_order"
        )
        cond_issues = sum(
            1 for i in issues if i["type"] == "conditional_completeness"
        )
        self.log("observe",
                 f"Found {report['total_issues']} consistency issues: "
                 f"{format_issues} format, {case_issues} case, "
                 f"{order_issues} date order, {cond_issues} conditional")

    def reply(self):
        self.summarize_issues(
            self.state.consistency_report["issues"],
            "consistency_summary", "consistency",
        )
