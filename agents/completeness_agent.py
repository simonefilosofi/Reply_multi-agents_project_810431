from agents.base_agent import BaseAgent, SMART


class CompletenessAgent(BaseAgent):
    name = "completeness"
    model = SMART

    def run(self):
        df = self.state.df_raw
        issues = []

        for col in df.columns:
            total = len(df)
            empty = df[col].isna().sum() + (df[col].astype(str).str.strip() == "").sum()
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

        self.state.completeness_report = {"issues": issues, "total_issues": len(issues)}

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

        print(f"[Completeness] {len(issues)} issues found.")
