import pandas as pd
from agents.base_agent import BaseAgent, SMART


class SchemaAgent(BaseAgent):
    name = "schema"
    model = SMART

    def run(self):
        df = self.state.df_raw
        fp = self.state.dataset_fingerprint
        issues = []

        for col in fp.get("numerical_columns", []):
            if col not in df.columns:
                continue
            non_empty = df[col].dropna()
            non_empty = non_empty[non_empty.astype(str).str.strip() != ""]
            num_frac = pd.to_numeric(non_empty, errors="coerce").notna().mean()
            if num_frac < 0.80:
                issues.append({
                    "column": col,
                    "type": "mixed_type",
                    "detail": f"Expected numeric but only {num_frac:.0%} values parse as numbers",
                    "severity": "high",
                })

        for col in fp.get("date_columns", []):
            if col not in df.columns:
                continue
            non_empty = df[col].dropna()
            non_empty = non_empty[non_empty.astype(str).str.strip() != ""]
            bad_frac = pd.to_datetime(non_empty, errors="coerce", dayfirst=True).isna().mean()
            if bad_frac > 0.10:
                issues.append({
                    "column": col,
                    "type": "invalid_dates",
                    "detail": f"{bad_frac:.0%} values cannot be parsed as dates",
                    "severity": "medium",
                })

        self.state.schema_report = {"issues": issues, "total_issues": len(issues)}

        issues_text = "\n".join(
            f"- [{i['severity'].upper()}] {i['column']}: {i['detail']}" for i in issues
        ) or "No schema issues found."

        try:
            self.state.schema_summary = self.call_llm(
                "You are a data quality analyst. Summarize these schema issues in 2-3 sentences.",
                f"Schema issues:\n{issues_text}"
            ).strip()
        except Exception:
            self.state.schema_summary = f"{len(issues)} schema issues found."

        print(f"[Schema] {len(issues)} issues found.")
