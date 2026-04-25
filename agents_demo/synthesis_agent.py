"""Layer 2 synthesis / supervisor agent. Collects and prioritizes all issues
from Layer 1 agents, performs cross-agent convergence analysis via LLM,
detects inter-agent conflicts, recalibrates severity based on compounding
evidence, computes the pre-remediation reliability score, and generates
an executive summary of data quality findings."""

from agents_demo.base_agent import BaseAgent, SMART
from state_demo.constants import SEVERITY_RANK
from state_demo.scoring import compute_reliability_score


class SynthesisAgent(BaseAgent):
    name = "synthesis_supervisor"
    model = SMART

    INSTRUCTION = (
        "You are a data quality synthesis supervisor. Your role is to review "
        "findings from multiple specialized agents, identify cross-cutting patterns "
        "and root causes, detect inter-agent conflicts, and generate executive-level "
        "summaries of data quality findings. When performing cross-agent analysis, "
        "be analytical and concise. For executive summaries, write 4-6 sentences "
        "highlighting the most critical problems and their business impact."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        sources = {
            "schema": self.state.schema_report,
            "completeness": self.state.completeness_report,
            "duplicate": self.state.duplicate_report,
            "anomaly": self.state.anomaly_report,
            "consistency": self.state.consistency_report,
            "constraint": self.state.constraint_report,
        }

        all_issues = []
        for source, report in sources.items():
            for issue in report.get("issues", []):
                all_issues.append({**issue, "source": source})

        all_issues.sort(
            key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2)
        )
        self.state.prioritized_issues = all_issues

        column_issues: dict = {}
        for issue in all_issues:
            col = issue.get("column", "")
            column_issues.setdefault(col, []).append(issue)

        self._column_convergence_analysis(column_issues)
        self._conflict_detection()
        self._severity_recalibration(column_issues)

    def _column_convergence_analysis(self, column_issues: dict):
        multi_agent_cols = {
            col: issues for col, issues in column_issues.items()
            if len(set(i["source"] for i in issues)) >= 2
        }
        if len(multi_agent_cols) > 5:
            sorted_cols = sorted(
                multi_agent_cols,
                key=lambda c: min(
                    SEVERITY_RANK.get(i["severity"], 2)
                    for i in multi_agent_cols[c]
                ),
            )
            multi_agent_cols = {c: multi_agent_cols[c] for c in sorted_cols[:5]}

        for col, issues in multi_agent_cols.items():
            agents_involved = sorted(set(i["source"] for i in issues))
            agent_labels = [f"{a.title()}Agent" for a in agents_involved]
            issue_lines = "\n".join(
                f"  - {i['source'].title()}Agent: {i['detail']}" for i in issues
            )
            self.log("act",
                     f"Querying {' and '.join(agent_labels)} about "
                     f"column '{col}': {len(agents_involved)} agents "
                     f"flagged issues that may share a root cause.")

            user = (
                f"Column '{col}' was flagged by multiple agents:\n{issue_lines}\n\n"
                f"Reason about whether these findings share a root cause. "
                f'Respond ONLY with a JSON object, no other text: '
                f'{{"root_cause": "...", "recommendation": "..."}}'
            )
            try:
                result = self.call_llm_json(user, max_tokens=512)
                root_cause = result.get("root_cause", "undetermined")
                recommendation = result.get("recommendation", "manual review")
            except Exception as e:
                self.log("error", f"LLM cross-agent analysis failed for '{col}': {e}")
                root_cause = (
                    "Multiple quality dimensions affected -- manual review recommended."
                )
                recommendation = "Inspect column in source system."

            insight = {
                "insight": (
                    f"Column '{col}' flagged by {len(agents_involved)} agents: "
                    f"{root_cause}"
                ),
                "related_agents": agents_involved,
                "related_columns": [col],
                "action_taken": recommendation,
            }
            self.state.cross_agent_insights.append(insight)
            self.log("act", f"Cross-reference result for column '{col}': {root_cause}")

    def _conflict_detection(self):
        fp = self.state.dataset_fingerprint
        num_cols = set(fp.get("numerical_columns", []))
        for issue in self.state.schema_report.get("issues", []):
            if (
                issue["type"] == "mixed_type"
                and issue["column"] in num_cols
                and issue["severity"] == "high"
            ):
                detail = (
                    f"Conflict: ProfilerAgent classified '{issue['column']}' as "
                    f"numerical, but SchemaAgent found it mostly non-numeric "
                    f"({issue['detail']}). Column classification may need revision."
                )
                self.log("act", detail)
                self.state.cross_agent_insights.append({
                    "insight": detail,
                    "related_agents": ["profiler", "schema"],
                    "related_columns": [issue["column"]],
                    "action_taken": "Review column classification",
                })

    def _severity_recalibration(self, column_issues: dict):
        for col, issues in column_issues.items():
            medium_issues = [i for i in issues if i["severity"] == "medium"]
            medium_agents = set(i["source"] for i in medium_issues)
            if len(medium_agents) >= 2:
                for issue in medium_issues:
                    issue["severity"] = "high"
                self.log("act",
                         f"Severity recalibrated: '{col}' has medium issues from "
                         f"{len(medium_agents)} different agents "
                         f"({', '.join(sorted(medium_agents))}) -- upgraded to high")
        self.state.prioritized_issues.sort(
            key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2)
        )

    def observe(self):
        score, dimensions = compute_reliability_score(self.state.df_raw, self.state)
        self.state.reliability_score_before = score
        issues = self.state.prioritized_issues
        high = sum(1 for i in issues if i["severity"] == "high")
        medium = sum(1 for i in issues if i["severity"] == "medium")
        low = sum(1 for i in issues if i["severity"] == "low")
        dim_text = ", ".join(f"{k}={v:.2f}" for k, v in dimensions.items())
        self.log("observe",
                 f"{len(issues)} issues prioritized: "
                 f"{high} high, {medium} medium, {low} low. "
                 f"Pre-remediation reliability score: {score}/100 ({dim_text})")

    def reply(self):
        all_issues = self.state.prioritized_issues
        sources = set(i["source"] for i in all_issues)
        top = all_issues[:10]
        top_text = "\n".join(
            f"- [{i['severity'].upper()}] ({i['source']}) {i['column']}: {i['detail']}"
            for i in top
        ) or "No issues found."
        summaries = "\n".join(filter(None, [
            self.state.schema_summary,
            self.state.completeness_summary,
            self.state.duplicate_summary,
            self.state.anomaly_summary,
            self.state.consistency_summary,
            self.state.constraint_summary,
        ]))
        insights_text = "\n".join(
            f"- {ins['insight']}: {ins['action_taken']}"
            for ins in self.state.cross_agent_insights
        ) or "No cross-agent insights."

        user = (
            f"Task: {self.prompt}\n\n"
            f"Dataset domain: "
            f"{self.state.dataset_fingerprint.get('domain', 'unknown')}\n"
            f"Total issues found: {len(all_issues)}\n"
            f"Pre-remediation reliability score: "
            f"{self.state.reliability_score_before}/100\n\n"
            f"Top issues:\n{top_text}\n\n"
            f"Agent summaries:\n{summaries}\n\n"
            f"Cross-agent insights:\n{insights_text}\n\n"
            f"Write a concise executive summary (4-6 sentences) highlighting "
            f"the most critical problems and their business impact."
        )
        try:
            self.state.synthesis_summary = self.call_llm(user).strip()
        except Exception as e:
            self.log("error", str(e))
            self.state.synthesis_summary = (
                f"{len(all_issues)} issues found across {len(sources)} agents. "
                f"Pre-remediation reliability score: "
                f"{self.state.reliability_score_before:.1f}/100."
            )
        self.log("reply", self.state.synthesis_summary)
