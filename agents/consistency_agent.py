import re
import pandas as pd
from itertools import combinations
from agents.base_agent import BaseAgent, SMART

DATE_PATTERNS = {
    "DD/MM/YYYY": r"^\d{2}/\d{2}/\d{4}$",
    "YYYY-MM-DD": r"^\d{4}-\d{2}-\d{2}$",
    "DD-MM-YYYY": r"^\d{2}-\d{2}-\d{4}$",
    "DD.MM.YYYY": r"^\d{2}\.\d{2}\.\d{4}$",
    "MM/DD/YYYY": r"^\d{2}/\d{2}/\d{4}$",
}


class ConsistencyAgent(BaseAgent):
    name = "consistency"
    model = SMART

    def run(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        date_cols = [c for c in fp.get("date_columns", []) if c in df.columns]

        # --- Format consistency within each date column ---
        for col in date_cols:
            sample = df[col].dropna().astype(str).str.strip()
            found_formats = [
                fmt for fmt, pat in DATE_PATTERNS.items()
                if sample.str.match(pat).any()
            ]
            if len(found_formats) > 1:
                issues.append({
                    "column": col,
                    "type": "mixed_date_formats",
                    "detail": f"Multiple date formats detected: {', '.join(found_formats)}",
                    "severity": "medium",
                })

        # --- Date ordering between column pairs ---
        for col_a, col_b in combinations(date_cols, 2):
            parsed_a = pd.to_datetime(df[col_a], errors="coerce", dayfirst=True)
            parsed_b = pd.to_datetime(df[col_b], errors="coerce", dayfirst=True)
            both_valid = parsed_a.notna() & parsed_b.notna()
            if both_valid.sum() < 10:
                continue
            violations = int((parsed_a[both_valid] > parsed_b[both_valid]).sum())
            if violations > 0:
                issues.append({
                    "column": f"{col_a} / {col_b}",
                    "type": "date_order",
                    "detail": f"{violations} rows where '{col_a}' is later than '{col_b}'",
                    "severity": "high" if violations / both_valid.sum() > 0.05 else "medium",
                })

        # Check conditional completeness between columns that share a name prefix
        # (likely related fields, e.g. "data_inizio" / "data_fine")
        col_list = list(df.columns)
        related_pairs = [
            (col_a, col_b)
            for col_a, col_b in combinations(col_list, 2)
            if col_a.split("_")[0].lower() == col_b.split("_")[0].lower()
        ]
        for col_a, col_b in related_pairs:
            filled_a = df[col_a].notna() & (df[col_a].astype(str).str.strip() != "")
            filled_b = df[col_b].notna() & (df[col_b].astype(str).str.strip() != "")
            if filled_a.sum() < 10:
                continue
            fill_rate = filled_b[filled_a].mean()
            if 0.90 <= fill_rate < 1.0:
                missing_when_a = int((filled_a & ~filled_b).sum())
                issues.append({
                    "column": f"{col_a} / {col_b}",
                    "type": "conditional_completeness",
                    "detail": f"{missing_when_a} rows have '{col_a}' filled but '{col_b}' empty",
                    "severity": "low",
                })

        self.state.consistency_report = {"issues": issues, "total_issues": len(issues)}

        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}" for i in issues
        ) or "No consistency issues found."

        try:
            self.state.consistency_summary = self.call_llm(
                "You are a data quality analyst. Summarize these consistency issues in 2-3 sentences.",
                f"Consistency issues:\n{issues_text}"
            ).strip()
        except Exception:
            self.state.consistency_summary = f"{len(issues)} consistency issues found."

        print(f"[Consistency] {len(issues)} issues found.")
