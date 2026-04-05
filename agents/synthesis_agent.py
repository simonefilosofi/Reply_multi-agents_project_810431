from agents.base_agent import BaseAgent, SMART

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


class SynthesisAgent(BaseAgent):
    name = "synthesis"
    model = SMART

    def run(self):
        # Collect all issues from Layer 1, tagging each with its source
        sources = {
            "schema": self.state.schema_report,
            "completeness": self.state.completeness_report,
            "duplicate": self.state.duplicate_report,
            "anomaly": self.state.anomaly_report,
            "consistency": self.state.consistency_report,
        }

        all_issues = []
        for source, report in sources.items():
            for issue in report.get("issues", []):
                all_issues.append({**issue, "source": source})

        # Sort by severity
        all_issues.sort(key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2))

        self.state.prioritized_issues = all_issues

        # LLM executive summary
        top = all_issues[:10]
        top_text = "\n".join(
            f"- [{i['severity'].upper()}] ({i['source']}) {i['column']}: {i['detail']}"
            for i in top
        ) or "No issues found."

        summaries = "\n".join([
            self.state.schema_summary,
            self.state.completeness_summary,
            self.state.duplicate_summary,
            self.state.anomaly_summary,
            self.state.consistency_summary,
        ])

        system = (
            "You are a data quality analyst. Given the top issues and agent summaries "
            "from a data quality pipeline, write a concise executive summary (4-6 sentences) "
            "highlighting the most critical problems and their business impact."
        )
        user = (
            f"Dataset domain: {self.state.dataset_fingerprint.get('domain', 'unknown')}\n"
            f"Total issues found: {len(all_issues)}\n\n"
            f"Top issues:\n{top_text}\n\n"
            f"Agent summaries:\n{summaries}"
        )

        try:
            self.state.synthesis_summary = self.call_llm(system, user).strip()
        except Exception:
            self.state.synthesis_summary = f"{len(all_issues)} total issues prioritized."

        print(f"[Synthesis] {len(all_issues)} issues prioritized "
              f"({sum(1 for i in all_issues if i['severity'] == 'high')} high, "
              f"{sum(1 for i in all_issues if i['severity'] == 'medium')} medium, "
              f"{sum(1 for i in all_issues if i['severity'] == 'low')} low).")
