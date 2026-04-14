"""Layer 3 remediation agent. Applies automated fixes for data quality issues
identified by Layer 1 agents, logs all actions to the fix log, and uses LLM
reasoning for ambiguous remediation decisions."""

from collections import defaultdict

from agents_demo.base_agent import BaseAgent, SMART
from state_demo.helpers import missing_mask
from tools import (
    cap_outliers,
    fill_missing_categorical,
    fill_missing_numerical,
    fix_column_naming,
    fix_invalid_dates,
    fix_mixed_type,
    normalize_case,
    remove_duplicate_rows,
    standardize_date_format,
)


class RemediationAgent(BaseAgent):
    name = "remediation"
    model = SMART

    INSTRUCTION = (
        "You are a data quality remediation specialist. You plan and apply "
        "automated fixes for data quality issues, making conservative decisions "
        "that preserve data integrity. For ambiguous missing-value cases, you "
        "recommend the best imputation strategy. "
        "Always respond with a JSON object: "
        '{"strategy": "median" | "mode" | "flag", "reason": "..."}'
    )

    def think(self):
        issues = self.state.prioritized_issues
        insights = self.state.cross_agent_insights
        auto_types = {
            "duplicate_rows", "outliers", "mixed_type", "naming_convention",
            "format_inconsistency", "case_inconsistency", "missing_values",
            "invalid_dates",
        }
        auto_count = sum(1 for i in issues if i["type"] in auto_types)
        flag_count = len(issues) - auto_count
        self.log("think",
                 f"{self.prompt} | Planning remediation for {len(issues)} issues "
                 f"({auto_count} auto-fixable, {flag_count} flag-only). "
                 f"{len(insights)} cross-agent insights available.")

    def act(self):
        df = self.state.df_raw.copy()
        fp = self.state.dataset_fingerprint

        issues_by_type: dict = defaultdict(list)
        for issue in self.state.prioritized_issues:
            issues_by_type[issue["type"]].append(issue)

        for issue in issues_by_type.get("mixed_type", []):
            col = issue["column"]
            coerced = fix_mixed_type(df, col)
            self._log_fix(issue, "auto_fixed",
                          f"Coerced to numeric -- {coerced} non-numeric values became NaN",
                          coerced)

        for issue in issues_by_type.get("invalid_dates", []):
            col = issue["column"]
            method, valid = fix_invalid_dates(df, col)
            self._log_fix(issue, "auto_fixed",
                          f"Re-parsed dates ({method}) -- "
                          f"{valid}/{len(df)} values parsed successfully",
                          valid)

        if issues_by_type.get("duplicate_rows"):
            removed = remove_duplicate_rows(df)
            self._log_fix(
                {"type": "duplicate_rows", "column": "_rows_"},
                "auto_fixed",
                f"Removed {removed} duplicate rows (kept first occurrence)",
                removed,
            )

        for issue in issues_by_type.get("missing_values", []):
            self._fix_missing_values(df, issue, fp)

        for issue in issues_by_type.get("outliers", []):
            col = issue["column"]
            lower, upper, count = cap_outliers(df, col, self.state.df_raw[col])
            if count > 0:
                self._log_fix(issue, "auto_fixed",
                              f"Capped {count} outliers to [{lower:.2f}, {upper:.2f}] (3-sigma)",
                              count)

        for issue in issues_by_type.get("format_inconsistency", []):
            col = issue.get("column", "")
            action, detail = standardize_date_format(df, col)
            self._log_fix(issue, action, detail,
                          0 if action == "flagged_for_review" else 1)

        for issue in issues_by_type.get("case_inconsistency", []):
            col = issue.get("column", "")
            changed = normalize_case(df, col)
            self._log_fix(issue, "auto_fixed",
                          f"Normalized {changed} values to most frequent casing variant",
                          changed)

        for issue in issues_by_type.get("naming_convention", []):
            col = issue["column"]
            old, new = fix_column_naming(df, col)
            if new != old:
                self._log_fix(issue, "auto_fixed",
                              f"Renamed '{old}' -> '{new}'", 0,
                              old=old, new=new)

        for flag_type in (
            "sparse_column", "duplicate_columns", "duplicate_key",
            "date_order", "rare_categories", "conditional_completeness",
        ):
            for issue in issues_by_type.get(flag_type, []):
                self._flag_issue(issue)

        self.state.df_cleaned = df

    def _fix_missing_values(self, df, issue, fp):
        col = issue["column"]
        if col not in df.columns:
            return
        is_missing = missing_mask(df[col])
        rows_affected = int(is_missing.sum())
        if rows_affected == 0:
            return

        num_cols = set(fp.get("numerical_columns", []))
        date_cols = set(fp.get("date_columns", []))
        cat_cols = set(fp.get("categorical_columns", []))

        if col in num_cols:
            success, detail = fill_missing_numerical(df, col, is_missing)
            action = "auto_fixed" if success else "flagged_for_review"
            self._log_fix(issue, action, detail, rows_affected)
        elif col in date_cols:
            self._log_fix(
                issue, "flagged_for_review",
                f"Date column with {rows_affected} missing values "
                f"-- requires domain knowledge to impute",
                rows_affected,
            )
        elif col in cat_cols:
            success, detail = fill_missing_categorical(
                df, col, is_missing, issue["severity"]
            )
            action = "auto_fixed" if success else "flagged_for_review"
            self._log_fix(issue, action, detail, rows_affected)
        else:
            strategy = self._ask_llm_strategy(col, issue, fp)
            if strategy == "median":
                success, detail = fill_missing_numerical(df, col, is_missing)
                action = "auto_fixed" if success else "flagged_for_review"
                self._log_fix(issue, action, detail, rows_affected)
            elif strategy == "mode":
                success, detail = fill_missing_categorical(
                    df, col, is_missing, issue["severity"]
                )
                action = "auto_fixed" if success else "flagged_for_review"
                self._log_fix(issue, action, detail, rows_affected)
            else:
                self._log_fix(
                    issue, "flagged_for_review",
                    f"Unclassified column with {rows_affected} missing values "
                    f"-- flagged for human review",
                    rows_affected,
                )

    def _ask_llm_strategy(self, col: str, issue: dict, fp: dict) -> str:
        domain = fp.get("domain", "unknown")
        user = (
            f"Column '{col}' has {issue['detail']}. "
            f"The dataset domain is '{domain}'. "
            f"Should this column be: (a) filled with median, "
            f"(b) filled with mode, or (c) left as-is for human review? "
            f'Respond ONLY with JSON: {{"strategy": "median"|"mode"|"flag", "reason": "..."}}'
        )
        try:
            result = self.call_llm_json(user, max_tokens=512)
            strategy = result.get("strategy", "flag")
            reason = result.get("reason", "")
            self.log("act", f"LLM strategy for '{col}': {strategy} -- {reason}")
            return strategy if strategy in ("median", "mode", "flag") else "flag"
        except Exception as e:
            self.log("error", f"LLM remediation strategy failed for '{col}': {e}")
            return "flag"

    def _flag_issue(self, issue):
        descriptions = {
            "sparse_column": "Recommended for removal -- requires domain review",
            "duplicate_columns": "Columns may contain redundant data -- review for removal",
            "duplicate_key": "Rows share key values but differ elsewhere -- manual review needed",
            "date_order": "Cannot auto-fix date ordering without domain knowledge",
            "rare_categories": "Suggest grouping into 'Other' -- requires domain approval",
            "conditional_completeness": "Related column has gaps -- requires domain knowledge",
        }
        desc = descriptions.get(issue["type"], "Flagged for human review")
        self._log_fix(issue, "flagged_for_review", desc, 0)

    def _log_fix(self, issue, action, description, rows_affected, **meta):
        entry = {
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

    def observe(self):
        df_raw = self.state.df_raw
        df_clean = self.state.df_cleaned
        rows_removed = len(df_raw) - len(df_clean)
        cols_renamed = sum(
            1 for f in self.state.fix_log
            if f["issue_type"] == "naming_convention" and f["action"] == "auto_fixed"
        )
        auto_fixed = sum(1 for f in self.state.fix_log if f["action"] == "auto_fixed")
        flagged = sum(1 for f in self.state.fix_log if f["action"] == "flagged_for_review")
        self.log("observe",
                 f"Remediation complete: {auto_fixed} auto-fixed, "
                 f"{flagged} flagged for review. "
                 f"Rows removed: {rows_removed}, "
                 f"columns renamed: {cols_renamed}. "
                 f"df_cleaned shape: {df_clean.shape}")

    def reply(self):
        fix_summary = "\n".join(
            f"- [{f['action']}] {f['column']}: {f['description']}"
            for f in self.state.fix_log
        ) or "No fixes applied."
        auto_fixed = sum(1 for f in self.state.fix_log if f["action"] == "auto_fixed")
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
                f"{auto_fixed} issues auto-remediated, "
                f"{flagged} issues flagged for human review."
            )
        self.state.remediation_plan = self.state.fix_log
        self.log("reply", narrative)
