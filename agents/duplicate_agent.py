# DuplicateAgent — Layer 1
# Detects three types of duplication:
# 1. Duplicate rows: fully identical records anywhere in the dataset.
# 2. Duplicate columns: pairs of columns flagged by the profiler as containing the same data.
# 3. Near-duplicate keys: values in ID/key columns that become identical after normalizing
#    whitespace and casing (e.g. " CF001 " vs "cf001").
# Detection is pure code; the LLM is called only to write a human-readable summary.

from agents.base_agent import BaseAgent, SMART


class DuplicateAgent(BaseAgent):
    name = "duplicate"
    model = SMART

    def run(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        # Duplicate rows
        dup_rows = int(df.duplicated().sum())
        if dup_rows > 0:
            issues.append({
                "column": "_rows_",
                "type": "duplicate_rows",
                "detail": f"{dup_rows} fully duplicate rows ({dup_rows/len(df):.1%} of dataset)",
                "severity": "high" if dup_rows / len(df) > 0.05 else "medium",
            })

        # Duplicate column pairs (from profiler)
        for pair in fp.get("likely_duplicate_pairs", []):
            if len(pair) == 2 and pair[0] in df.columns and pair[1] in df.columns:
                issues.append({
                    "column": f"{pair[0]} / {pair[1]}",
                    "type": "duplicate_columns",
                    "detail": f"Columns '{pair[0]}' and '{pair[1]}' appear to contain the same data",
                    "severity": "medium",
                })

        # Near-duplicate detection on key columns (whitespace + casing normalization)
        key_cols = [
            c for c in fp.get("suggested_key_columns", []) + fp.get("id_columns", [])
            if c in df.columns
        ]
        for col in key_cols:
            normalized = df[col].dropna().astype(str).str.strip().str.lower().str.replace(r"\s+", "", regex=True)
            exact_dups = int(df[col].dropna().duplicated().sum())
            near_dups = int(normalized.duplicated().sum())
            near_only = near_dups - exact_dups
            if near_only > 0:
                issues.append({
                    "column": col,
                    "type": "near_duplicate_keys",
                    "detail": f"{near_only} near-duplicate values after normalizing whitespace and casing",
                    "severity": "high",
                })

        self.state.duplicate_report = {"issues": issues, "total_issues": len(issues)}

        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}" for i in issues
        ) or "No duplicate issues found."

        try:
            self.state.duplicate_summary = self.call_llm(
                "You are a data quality analyst. Summarize these duplicate issues in 2-3 sentences.",
                f"Duplicate issues:\n{issues_text}"
            ).strip()
        except Exception:
            self.state.duplicate_summary = f"{len(issues)} duplicate issues found."

        print(f"[Duplicate] {len(issues)} issues found.")
