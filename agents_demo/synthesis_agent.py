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

    def think(self):
        self.log("think",
                 "Reviewing findings from all Layer 1 agents to identify "
                 "cross-cutting patterns and inter-agent conflicts")

    def act(self):
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

        all_issues.sort(
            key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2)
        )

        self.state.prioritized_issues = all_issues

        column_issues = {}
        for issue in all_issues:
            col = issue.get("column", "")
            if col not in column_issues:
                column_issues[col] = []
            column_issues[col].append(issue)

        self._column_convergence_analysis(column_issues)
        self._conflict_detection()
        self._severity_recalibration(column_issues)

    def _column_convergence_analysis(self, column_issues):
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
            multi_agent_cols = {
                c: multi_agent_cols[c] for c in sorted_cols[:5]
            }

        for col, issues in multi_agent_cols.items():
            agents_involved = sorted(set(i["source"] for i in issues))
            agent_labels = [f"{a.title()}Agent" for a in agents_involved]
            issue_lines = "\n".join(
                f"  - {i['source'].title()}Agent: {i['detail']}"
                for i in issues
            )

            self.log("act",
                     f"Querying {' and '.join(agent_labels)} about "
                     f"column '{col}': {len(agents_involved)} agents "
                     f"flagged issues that may share a root cause.")

            system = (
                "You are a data quality analyst. Reason about whether "
                "these findings share a root cause. Respond ONLY with a "
                "JSON object, no other text: "
                "{\"root_cause\": \"...\", \"recommendation\": \"...\"}"
            )
            user = (
                f"Column '{col}' was flagged by multiple agents:\n"
                f"{issue_lines}"
            )

            try:
                result = self.call_llm_json(system, user, max_tokens=512)
                root_cause = result.get("root_cause", "undetermined")
                recommendation = result.get("recommendation",
                                            "manual review")
            except Exception as e:
                self.log("error",
                         f"LLM cross-agent analysis failed for "
                         f"'{col}': {e}")
                root_cause = (
                    "Multiple quality dimensions affected -- "
                    "manual review recommended."
                )
                recommendation = "Inspect column in source system."

            insight = {
                "insight": (
                    f"Column '{col}' flagged by "
                    f"{len(agents_involved)} agents: {root_cause}"
                ),
                "related_agents": agents_involved,
                "related_columns": [col],
                "action_taken": recommendation,
            }
            self.state.cross_agent_insights.append(insight)

            self.log("act",
                     f"Cross-reference result for column '{col}': "
                     f"{root_cause}")

    def _conflict_detection(self):
        fp = self.state.dataset_fingerprint
        num_cols = set(fp.get("numerical_columns", []))

        for issue in self.state.schema_report.get("issues", []):
            if (issue["type"] == "mixed_type"
                    and issue["column"] in num_cols
                    and issue["severity"] == "high"):
                detail = (
                    f"Conflict: ProfilerAgent classified "
                    f"'{issue['column']}' as numerical, but "
                    f"SchemaAgent found it mostly non-numeric "
                    f"({issue['detail']}). Column classification "
                    f"may need revision."
                )
                self.log("act", detail)
                self.state.cross_agent_insights.append({
                    "insight": detail,
                    "related_agents": ["profiler", "schema"],
                    "related_columns": [issue["column"]],
                    "action_taken": "Review column classification",
                })

    def _severity_recalibration(self, column_issues):
        for col, issues in column_issues.items():
            medium_issues = [
                i for i in issues if i["severity"] == "medium"
            ]
            medium_agents = set(i["source"] for i in medium_issues)
            if len(medium_agents) >= 2:
                for issue in medium_issues:
                    issue["severity"] = "high"
                self.log("act",
                         f"Severity recalibrated: '{col}' has medium "
                         f"issues from {len(medium_agents)} different "
                         f"agents ({', '.join(sorted(medium_agents))}) "
                         f"-- upgraded to high")

        self.state.prioritized_issues.sort(
            key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2)
        )

    def observe(self):
        score, dimensions = compute_reliability_score(
            self.state.df_raw, self.state,
        )
        self.state.reliability_score_before = score

        issues = self.state.prioritized_issues
        high = sum(1 for i in issues if i["severity"] == "high")
        medium = sum(1 for i in issues if i["severity"] == "medium")
        low = sum(1 for i in issues if i["severity"] == "low")
        dim_text = ", ".join(
            f"{k}={v:.2f}" for k, v in dimensions.items()
        )
        self.log("observe",
                 f"{len(issues)} issues prioritized: "
                 f"{high} high, {medium} medium, {low} low. "
                 f"Pre-remediation reliability score: {score}/100 "
                 f"({dim_text})")

    def reply(self):
        all_issues = self.state.prioritized_issues
        sources = set(i["source"] for i in all_issues)

        top = all_issues[:10]
        top_text = "\n".join(
            f"- [{i['severity'].upper()}] ({i['source']}) "
            f"{i['column']}: {i['detail']}"
            for i in top
        ) or "No issues found."

        summaries = "\n".join(filter(None, [
            self.state.schema_summary,
            self.state.completeness_summary,
            self.state.duplicate_summary,
            self.state.anomaly_summary,
            self.state.consistency_summary,
        ]))

        insights_text = "\n".join(
            f"- {ins['insight']}: {ins['action_taken']}"
            for ins in self.state.cross_agent_insights
        ) or "No cross-agent insights."

        system = (
            "You are a data quality analyst. Given the top issues, "
            "agent summaries, and cross-agent insights from a data "
            "quality pipeline, write a concise executive summary "
            "(4-6 sentences) highlighting the most critical problems "
            "and their business impact."
        )
        user = (
            f"Dataset domain: "
            f"{self.state.dataset_fingerprint.get('domain', 'unknown')}\n"
            f"Total issues found: {len(all_issues)}\n"
            f"Pre-remediation reliability score: "
            f"{self.state.reliability_score_before}/100\n\n"
            f"Top issues:\n{top_text}\n\n"
            f"Agent summaries:\n{summaries}\n\n"
            f"Cross-agent insights:\n{insights_text}"
        )

        try:
            self.state.synthesis_summary = self.call_llm(
                system, user,
            ).strip()
        except Exception as e:
            self.log("error", str(e))
            self.state.synthesis_summary = (
                f"{len(all_issues)} issues found across "
                f"{len(sources)} agents. "
                f"Pre-remediation reliability score: "
                f"{self.state.reliability_score_before:.1f}/100."
            )

        self.log("reply", self.state.synthesis_summary)

