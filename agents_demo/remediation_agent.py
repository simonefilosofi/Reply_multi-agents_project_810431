"""Layer 3 RemediationAgent (Step 11 restructure).

Thin TAOR orchestrator over the strategy registry in
``agents_demo.remediation_strategies``. ``act()`` walks ``STRATEGY_ORDER``
once, mutates ``df`` in place, then runs an LLM gap-detection pass on the
cleaned frame and enqueues residual issues into ``state.gap_issues`` for the
code-validator node (Step 12 wires the validator as a standalone graph node;
this layer no longer invokes it inline).

Public surface used by strategies:
* ``log_fix(issue, action, description, rows_affected, **meta)`` -- canonical
  fix-log writer; also emits a structured ``act`` log line.
* ``log(stage, message)`` -- inherited from :class:`BaseAgent`.
* ``ask_llm_strategy(col, issue, fp)`` -- LLM dispatcher used by
  :class:`MissingValuesStrategy` for unclassified columns.
* ``state`` -- the shared :class:`PipelineState` (strategies read
  ``state.df_raw``, ``state.fix_log``, ``state.dataset_fingerprint``).
"""

from collections import defaultdict
from typing import Any

import pandas as pd

from agents_demo.base_agent import SMART, BaseAgent
from agents_demo.remediation_strategies import STRATEGY_ORDER
from state_demo.constants import GAP_DETECTION_ISSUE_TYPES, ISSUE_TYPES, SEVERITY_RANK
from state_demo.helpers import non_empty_values
from state_demo.issues import Issue


class RemediationAgent(BaseAgent):
    name = "remediation"
    model = SMART

    INSTRUCTION = (
        "You are a data quality remediation specialist. You plan and apply "
        "automated fixes for data quality issues, making conservative decisions "
        "that preserve data integrity. For ambiguous missing-value cases, you "
        "recommend the best imputation strategy."
    )

    _AUTO_FIX_TYPES: frozenset[str] = frozenset(
        t for strategy in STRATEGY_ORDER for t in strategy.applies_to
    )

    def think(self) -> None:
        issues = self.state.prioritized_issues
        insights = self.state.cross_agent_insights
        auto_count = sum(1 for i in issues if i["type"] in self._AUTO_FIX_TYPES)
        flag_count = len(issues) - auto_count
        self.log(
            "think",
            f"{self.prompt} | Planning remediation for {len(issues)} issues "
            f"({auto_count} auto-fixable, {flag_count} flag-only). "
            f"{len(insights)} cross-agent insights available.",
        )

    def act(self) -> None:
        df = self.state.df_raw.copy()
        fp = self.state.dataset_fingerprint

        issues_by_type: dict[str, list[Issue]] = defaultdict(list)
        for issue in self.state.prioritized_issues:
            issues_by_type[issue["type"]].append(issue)

        for strategy in STRATEGY_ORDER:
            strategy.apply(df, issues_by_type, fp, self)

        self.state.df_cleaned = df

        gap_issues = self._run_gap_detection(df)
        if gap_issues:
            self.state.gap_issues = list(gap_issues)
            self.log(
                "act",
                f"Enqueued {len(gap_issues)} gap issue(s) into state.gap_issues "
                f"for the code-validator node",
            )

    def log_fix(
        self,
        issue: Issue | dict[str, Any],
        action: str,
        description: str,
        rows_affected: int,
        **meta: Any,
    ) -> None:
        entry: dict[str, Any] = {
            "issue_type": issue["type"],
            "column": issue.get("column", ""),
            "action": action,
            "description": description,
            "rows_affected": rows_affected,
        }
        if meta:
            entry["metadata"] = meta
        self.state.fix_log.append(entry)
        self.log("act", f"[{action}] {issue.get('column', '')}: {description}")

    def ask_llm_strategy(self, col: str, issue: Issue | dict[str, Any], fp: dict[str, Any]) -> str:
        domain = fp.get("domain", "unknown")
        detail = issue.get("detail", "")
        user = (
            f"Column '{col}' has {detail}. "
            f"The dataset domain is '{domain}'. "
            f"Should this column be: (a) filled with median, "
            f"(b) filled with mode, or (c) left as-is for human review? "
            f'Respond ONLY with JSON: {{"strategy": "median"|"mode"|"flag", "reason": "..."}}'
        )
        try:
            result = self.call_llm_json(user, max_tokens=512, required_keys=["strategy"])
            strategy = result.get("strategy", "flag")
            reason = result.get("reason", "")
            self.log("act", f"LLM strategy for '{col}': {strategy} -- {reason}")
            return strategy if strategy in ("median", "mode", "flag") else "flag"
        except Exception as e:
            self.log("error", f"LLM remediation strategy failed for '{col}': {e}")
            return "flag"

    def _run_gap_detection(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        fixed_per_col: dict[str, list[str]] = {}
        for f in self.state.fix_log:
            if f["action"] == "auto_fixed":
                col = f["column"]
                fixed_per_col.setdefault(col, []).append(f"{f['issue_type']}: {f['description']}")

        handled_pairs = {(f["issue_type"], f["column"]) for f in self.state.fix_log}

        sections: list[str] = []
        for col in df.columns:
            nev = non_empty_values(df[col])
            if len(nev) == 0:
                continue
            sample = list(nev.sample(min(50, len(nev)), random_state=42).astype(str))
            dtype = str(df[col].dtype)
            already_fixed = fixed_per_col.get(col, [])
            sections.append(
                f"Column: '{col}' (dtype: {dtype})\n"
                f"Sample (current cleaned values): {sample}\n"
                f"Already fixed for this column: "
                f"{already_fixed if already_fixed else ['nothing']}"
            )

        if not sections:
            return []

        allowed_types_text = "\n".join(
            f"  {t}: {ISSUE_TYPES[t]}" for t in sorted(GAP_DETECTION_ISSUE_TYPES)
        )

        user = (
            f"Dataset domain: "
            f"{self.state.dataset_fingerprint.get('domain', 'unknown')}\n\n"
            + "\n\n".join(sections)
            + "\n\nYou are looking for data quality issues that REMAIN in the "
            "current cleaned values AFTER all automated fixes have been applied. "
            "The samples above show the CURRENT state of the data.\n\n"
            "Rules:\n"
            "- Only report issues clearly visible in the current sample values\n"
            "- Do NOT re-report issues listed in 'Already fixed for this column'\n"
            "- Do NOT flag missing values, sparse columns, duplicates, or naming issues\n"
            "- Each issue must be fixable with a simple pandas transformation\n"
            "- Use .astype(str) before any .str operations on non-object columns\n"
            "- If nothing new remains, return an empty list\n\n"
            f"Allowed issue types (use ONLY these):\n{allowed_types_text}\n\n"
            'Return JSON: {"gap_issues": [{"column": "...", "type": "...", '
            '"detail": "...", "severity": "high|medium|low", '
            '"filter": "pandas boolean expression selecting affected rows"}]}'
        )

        try:
            result = self.call_llm_json(user, max_tokens=2048, required_keys=["gap_issues"])
            raw_gap_issues = result.get("gap_issues", [])
            valid: list[dict[str, Any]] = []
            for issue in raw_gap_issues:
                col = issue.get("column", "")
                itype = issue.get("type", "")
                if not col or not itype:
                    continue
                if col not in df.columns:
                    continue
                if itype not in GAP_DETECTION_ISSUE_TYPES:
                    self.log("act", f"Gap issue rejected -- type '{itype}' not in vocabulary")
                    continue
                if (itype, col) in handled_pairs:
                    self.log("act", f"Gap issue rejected -- '{itype}' on '{col}' already handled")
                    continue
                if issue.get("severity") not in ("high", "medium", "low"):
                    continue
                valid.append({**issue, "source": "synthesis_gap_detection"})
                self.log(
                    "act",
                    f"Post-remediation gap: '{col}' [{itype}] -- {issue.get('detail', '')}",
                )
            self.log(
                "act",
                f"Post-remediation gap detection complete -- {len(valid)} issue(s) found",
            )
            if valid:
                self.state.prioritized_issues.sort(
                    key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2)
                )
            return valid
        except Exception as e:
            self.log("error", f"Post-remediation gap detection failed: {e}")
            return []

    def observe(self) -> None:
        df_raw = self.state.df_raw
        df_clean = self.state.df_cleaned if self.state.df_cleaned is not None else df_raw
        rows_removed = len(df_raw) - len(df_clean)
        cols_renamed = sum(
            1
            for f in self.state.fix_log
            if f["issue_type"] == "naming_convention" and f["action"] == "auto_fixed"
        )
        auto_fixed = sum(
            1 for f in self.state.fix_log if f["action"] in ("auto_fixed", "auto_fixed_by_llm")
        )
        flagged = sum(1 for f in self.state.fix_log if f["action"] == "flagged_for_review")
        self.log(
            "observe",
            f"Remediation complete: {auto_fixed} auto-fixed, "
            f"{flagged} flagged for review. "
            f"Rows removed: {rows_removed}, "
            f"columns renamed: {cols_renamed}. "
            f"df_cleaned shape: {df_clean.shape}",
        )

    def reply(self) -> None:
        fix_summary = (
            "\n".join(
                f"- [{f['action']}] {f['column']}: {f['description']}" for f in self.state.fix_log
            )
            or "No fixes applied."
        )
        auto_fixed = sum(
            1 for f in self.state.fix_log if f["action"] in ("auto_fixed", "auto_fixed_by_llm")
        )
        flagged = sum(1 for f in self.state.fix_log if f["action"] == "flagged_for_review")

        user = (
            f"Task: {self.prompt}\n\n"
            f"Fix actions:\n{fix_summary}\n\n"
            f"Write a concise summary (3-5 sentences) of what was remediated "
            f"and what was flagged for human review."
        )
        try:
            narrative = self.call_llm(user).strip()
        except Exception as e:
            self.log("error", str(e))
            narrative = (
                f"{auto_fixed} issues auto-remediated, {flagged} issues flagged for human review."
            )
        self.state.remediation_plan = self.state.fix_log
        self.log("reply", narrative)
