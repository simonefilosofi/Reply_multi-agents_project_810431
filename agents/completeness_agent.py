# CompletenessAgent — Layer 1
# Measures how complete the dataset is at three levels:
# 1. Per-column: flags columns with too many missing or placeholder values
#    (NaN, empty string, "N/A", "-", "unknown", etc.).
# 2. Overall: computes a single completeness rate for the entire dataset.
# 3. Row-level: flags rows where more than 50% of fields are empty.
# Detection is pure code; the LLM is called only to write a human-readable summary.

import pandas as pd
from agents.base_agent import BaseAgent, SMART

PLACEHOLDERS = {"n/a", "na", "null", "none", "-", "unknown", "?", "nd", ""}


def _is_missing(x) -> bool:
    return pd.isna(x) or str(x).strip().lower() in PLACEHOLDERS


class CompletenessAgent(BaseAgent):
    name = "completeness"
    model = SMART

    def run(self):
        df = self.state.df_raw
        issues = []

        missing_mask = df.apply(lambda col: col.map(_is_missing))

        for col in df.columns:
            total = len(df)
            empty = int(missing_mask[col].sum())
            rate = empty / total if total > 0 else 0

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
                "detail": f"{rate:.0%} of values are missing or empty ({empty}/{total})",
                "severity": severity,
            })

        # Overall dataset completeness rate 
        total_cells = df.size
        missing_cells = int(missing_mask.sum().sum())
        overall_rate = round(1 - missing_cells / total_cells, 4) if total_cells > 0 else 1.0

        #  Row-level completeness
        row_missing_rate = missing_mask.mean(axis=1)
        empty_rows = int((row_missing_rate > 0.5).sum())
        if empty_rows > 0:
            issues.append({
                "column": "_rows_",
                "type": "empty_rows",
                "detail": f"{empty_rows} rows are more than 50% empty",
                "severity": "high" if empty_rows / len(df) > 0.05 else "medium",
            })

        self.state.completeness_report = {
            "issues": issues,
            "total_issues": len(issues),
            "overall_rate": overall_rate,
            "sparse_columns": [i["column"] for i in issues if i["severity"] == "high" and i["type"] == "missing_values"],
        }

        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}" for i in issues
        ) or "No completeness issues found."

        try:
            self.state.completeness_summary = self.call_llm(
                "You are a data quality analyst. Summarize these completeness issues in 2-3 sentences.",
                f"Completeness issues:\n{issues_text}"
            ).strip()
        except Exception:
            self.state.completeness_summary = f"{len(issues)} completeness issues found."

        print(f"[Completeness] {len(issues)} issues found. Overall completeness: {overall_rate:.1%}")
