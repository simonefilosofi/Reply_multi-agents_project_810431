"""Layer 3 remediation agent. Applies automated fixes for data quality issues
identified by Layer 1 agents, logs all actions to the fix log, and uses LLM
reasoning for ambiguous remediation decisions. Implements placeholder-safe
mode fill and 3-sigma-consistent outlier capping."""

import re
from collections import defaultdict

import pandas as pd

from agents_demo.base_agent import BaseAgent, SMART
from state_demo.constants import DATE_FORMAT_MAP, DATE_PATTERNS, PLACEHOLDERS
from state_demo.helpers import missing_mask as compute_missing_mask


class RemediationAgent(BaseAgent):
    name = "remediation"
    model = SMART

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
                 f"Planning remediation for {len(issues)} issues "
                 f"({auto_count} auto-fixable, {flag_count} flag-only). "
                 f"{len(insights)} cross-agent insights available.")

    def act(self):
        df = self.state.df_raw.copy()
        fp = self.state.dataset_fingerprint

        issues_by_type = defaultdict(list)
        for issue in self.state.prioritized_issues:
            issues_by_type[issue["type"]].append(issue)

        for issue in issues_by_type.get("mixed_type", []):
            self._fix_mixed_type(df, issue)
        for issue in issues_by_type.get("invalid_dates", []):
            self._fix_invalid_dates(df, issue)

        if issues_by_type.get("duplicate_rows"):
            self._fix_duplicate_rows(df)

        for issue in issues_by_type.get("missing_values", []):
            self._fix_missing_values(df, issue, fp)

        for issue in issues_by_type.get("outliers", []):
            self._fix_outliers(df, issue)

        for issue in issues_by_type.get("format_inconsistency", []):
            self._fix_format_inconsistency(df, issue, fp)
        for issue in issues_by_type.get("case_inconsistency", []):
            self._fix_case_inconsistency(df, issue)

        for issue in issues_by_type.get("naming_convention", []):
            self._fix_naming_convention(df, issue)

        for flag_type in ("sparse_column", "duplicate_columns",
                          "duplicate_key", "date_order",
                          "rare_categories", "conditional_completeness"):
            for issue in issues_by_type.get(flag_type, []):
                self._flag_issue(issue)

        self.state.df_cleaned = df

    def _fix_mixed_type(self, df, issue):
        col = issue["column"]
        if col not in df.columns:
            return
        before_na = int(df[col].isna().sum())
        df[col] = pd.to_numeric(df[col], errors="coerce")
        coerced = int(df[col].isna().sum()) - before_na
        self._log_fix(issue, "auto_fixed",
                      f"Coerced to numeric -- "
                      f"{coerced} non-numeric values became NaN",
                      coerced)

    def _fix_invalid_dates(self, df, issue):
        col = issue["column"]
        if col not in df.columns:
            return
        parsed_df = pd.to_datetime(
            df[col], errors="coerce", dayfirst=True,
        )
        parsed_ndf = pd.to_datetime(
            df[col], errors="coerce", dayfirst=False,
        )
        df_valid = int(parsed_df.notna().sum())
        ndf_valid = int(parsed_ndf.notna().sum())

        if df_valid >= ndf_valid:
            df[col] = parsed_df
            method = "dayfirst=True"
            valid = df_valid
        else:
            df[col] = parsed_ndf
            method = "dayfirst=False"
            valid = ndf_valid

        self._log_fix(issue, "auto_fixed",
                      f"Re-parsed dates ({method}) -- "
                      f"{valid}/{len(df)} values parsed successfully",
                      valid)

    def _fix_duplicate_rows(self, df):
        before = len(df)
        df.drop_duplicates(inplace=True)
        df.reset_index(drop=True, inplace=True)
        removed = before - len(df)
        self._log_fix(
            {"type": "duplicate_rows", "column": "_rows_"},
            "auto_fixed",
            f"Removed {removed} duplicate rows (kept first occurrence)",
            removed,
        )

    def _fix_missing_values(self, df, issue, fp):
        col = issue["column"]
        if col not in df.columns:
            return

        num_cols = set(fp.get("numerical_columns", []))
        date_cols = set(fp.get("date_columns", []))
        cat_cols = set(fp.get("categorical_columns", []))

        is_missing = self._missing_mask(df, col)
        rows_affected = int(is_missing.sum())
        if rows_affected == 0:
            return

        if col in num_cols:
            self._fill_numerical(df, col, is_missing, rows_affected, issue)
        elif col in date_cols:
            self._log_fix(
                issue, "flagged_for_review",
                f"Date column with {rows_affected} missing values "
                f"-- requires domain knowledge to impute",
                rows_affected,
            )
        elif col in cat_cols:
            self._fill_categorical_or_flag(
                df, col, is_missing, rows_affected, issue,
            )
        else:
            strategy = self._ask_llm_strategy(col, issue, fp)
            if strategy == "median":
                self._fill_numerical(
                    df, col, is_missing, rows_affected, issue,
                )
            elif strategy == "mode":
                self._fill_categorical_or_flag(
                    df, col, is_missing, rows_affected, issue,
                )
            else:
                self._log_fix(
                    issue, "flagged_for_review",
                    f"Unclassified column with {rows_affected} missing "
                    f"values -- flagged for human review",
                    rows_affected,
                )

    def _fill_numerical(self, df, col, is_missing, rows_affected, issue):
        numeric = pd.to_numeric(df[col], errors="coerce")
        median_val = numeric.median()
        if pd.notna(median_val):
            df[col] = numeric.fillna(median_val)
            self._log_fix(
                issue, "auto_fixed",
                f"Filled {rows_affected} missing values "
                f"with median ({median_val:.2f})",
                rows_affected,
            )
        else:
            self._log_fix(
                issue, "flagged_for_review",
                "Cannot compute median -- all values non-numeric",
                rows_affected,
            )

    def _fill_categorical_or_flag(self, df, col, is_missing,
                                  rows_affected, issue):
        if issue["severity"] == "high":
            self._log_fix(
                issue, "flagged_for_review",
                f"Categorical column with {rows_affected} missing values "
                f"(>50%) -- recommended for removal or domain review",
                rows_affected,
            )
            return

        clean_series = df[col][
            ~df[col].astype(str).str.strip().str.lower().isin(PLACEHOLDERS)
            & df[col].notna()
            & (df[col].astype(str).str.strip() != "")
        ]
        if len(clean_series) > 0:
            mode_value = clean_series.mode().iloc[0]
            df.loc[is_missing, col] = mode_value
            self._log_fix(
                issue, "auto_fixed",
                f"Filled {rows_affected} missing/placeholder values "
                f"with mode ('{mode_value}')",
                rows_affected,
            )
        else:
            self._log_fix(
                issue, "flagged_for_review",
                "Column is entirely placeholders/empty -- "
                "cannot compute safe mode value",
                rows_affected,
            )

    def _ask_llm_strategy(self, col, issue, fp):
        domain = fp.get("domain", "unknown")
        system = (
            "You are a data quality remediation specialist. "
            "Respond ONLY with a JSON object, no other text: "
            "{\"strategy\": \"median\"|\"mode\"|\"flag\", "
            "\"reason\": \"...\"}"
        )
        user = (
            f"Column '{col}' has {issue['detail']}. "
            f"The dataset domain is '{domain}'. "
            f"Should this column be: (a) filled with median, "
            f"(b) filled with mode, (c) left as-is for human review?"
        )
        try:
            result = self.call_llm_json(system, user, max_tokens=512)
            strategy = result.get("strategy", "flag")
            reason = result.get("reason", "")
            self.log("act",
                     f"LLM strategy for '{col}': {strategy} -- {reason}")
            if strategy in ("median", "mode", "flag"):
                return strategy
            return "flag"
        except Exception as e:
            self.log("error",
                     f"LLM remediation strategy failed for '{col}': {e}")
            return "flag"

    def _fix_outliers(self, df, issue):
        col = issue["column"]
        if col not in df.columns:
            return
        raw_numeric = pd.to_numeric(
            self.state.df_raw[col], errors="coerce",
        )
        raw_valid = raw_numeric.dropna()
        if len(raw_valid) < 2:
            return
        mean = raw_valid.mean()
        std = raw_valid.std()
        if std == 0:
            return
        lower = mean - 3 * std
        upper = mean + 3 * std
        numeric = pd.to_numeric(df[col], errors="coerce")
        outlier_count = int(((numeric - mean).abs() > 3 * std).sum())
        if outlier_count > 0:
            df[col] = numeric.clip(lower=lower, upper=upper)
            self._log_fix(
                issue, "auto_fixed",
                f"Capped {outlier_count} outliers to "
                f"[{lower:.2f}, {upper:.2f}] (3-sigma)",
                outlier_count,
            )

    def _fix_format_inconsistency(self, df, issue, fp):
        col = issue.get("column", "")
        if col not in df.columns:
            return
        date_cols = set(fp.get("date_columns", []))

        if col in date_cols:
            self._standardize_date_format(df, col, issue)
        else:
            original = df[col].copy()
            df[col] = df[col].astype(str).str.strip()
            changed = int((df[col] != original).sum())
            self._log_fix(
                issue, "auto_fixed",
                f"Stripped whitespace from {changed} values",
                changed,
            )

    def _standardize_date_format(self, df, col, issue):
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            self._log_fix(
                issue, "auto_fixed",
                "Column already parsed as datetime -- "
                "format is standardized",
                int(df[col].notna().sum()),
            )
            return

        values = df[col].dropna().astype(str).str.strip()
        pattern_counts = {}
        for val in values:
            for label, regex in DATE_PATTERNS:
                if regex.match(val):
                    pattern_counts[label] = (
                        pattern_counts.get(label, 0) + 1
                    )
                    break

        if not pattern_counts:
            self._log_fix(issue, "flagged_for_review",
                          "No recognized date patterns found", 0)
            return

        dominant = max(pattern_counts, key=pattern_counts.get)
        fmt = DATE_FORMAT_MAP.get(dominant, "%d/%m/%Y")
        parsed = pd.to_datetime(
            df[col], errors="coerce", dayfirst=True,
        )
        reformatted = parsed.dt.strftime(fmt)
        reformatted[parsed.isna()] = pd.NA
        changed = int((reformatted != df[col].astype(str)).sum())
        df[col] = reformatted
        self._log_fix(
            issue, "auto_fixed",
            f"Standardized {changed} date values to {dominant} format",
            changed,
        )

    def _fix_case_inconsistency(self, df, issue):
        col = issue.get("column", "")
        if col not in df.columns:
            return
        original = df[col].copy()
        non_empty_mask = (
            df[col].notna()
            & (df[col].astype(str).str.strip() != "")
        )
        stripped = df[col].astype(str).str.strip()

        value_counts = stripped[non_empty_mask].value_counts()
        lower_to_best = {}
        for val in value_counts.index:
            key = val.lower()
            if key not in lower_to_best:
                lower_to_best[key] = val

        normalized = stripped.str.lower().map(lower_to_best)
        df.loc[non_empty_mask, col] = normalized[non_empty_mask]

        changed = int((df[col] != original).sum())
        self._log_fix(
            issue, "auto_fixed",
            f"Normalized {changed} values to most frequent casing variant",
            changed,
        )

    def _fix_naming_convention(self, df, issue):
        col = issue["column"]
        if col not in df.columns:
            return
        new_name = re.sub(r"[^a-z0-9]+", "_", col.lower().strip())
        new_name = new_name.strip("_")
        if not new_name:
            new_name = f"col_{list(df.columns).index(col)}"
        if new_name != col and new_name in df.columns:
            suffix = 2
            while f"{new_name}_{suffix}" in df.columns:
                suffix += 1
            new_name = f"{new_name}_{suffix}"
        if new_name != col:
            df.rename(columns={col: new_name}, inplace=True)
            self._log_fix(issue, "auto_fixed",
                          f"Renamed '{col}' -> '{new_name}'", 0,
                          old=col, new=new_name)

    def _flag_issue(self, issue):
        descriptions = {
            "sparse_column":
                "Recommended for removal -- requires domain review",
            "duplicate_columns":
                "Columns may contain redundant data -- review for removal",
            "duplicate_key":
                "Rows share key values but differ elsewhere "
                "-- manual review needed",
            "date_order":
                "Cannot auto-fix date ordering "
                "without domain knowledge",
            "rare_categories":
                "Suggest grouping into 'Other' "
                "-- requires domain approval",
            "conditional_completeness":
                "Related column has gaps "
                "-- requires domain knowledge",
        }
        desc = descriptions.get(
            issue["type"], "Flagged for human review",
        )
        self._log_fix(issue, "flagged_for_review", desc, 0)

    def _missing_mask(self, df, col):
        return compute_missing_mask(df[col])

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
        self.log("act",
                 f"[{action}] {issue.get('column', '')}: {description}")

    def observe(self):
        df_raw = self.state.df_raw
        df_clean = self.state.df_cleaned

        rows_removed = len(df_raw) - len(df_clean)
        cols_renamed = sum(
            1 for f in self.state.fix_log
            if f["issue_type"] == "naming_convention"
            and f["action"] == "auto_fixed"
        )
        auto_fixed = sum(
            1 for f in self.state.fix_log
            if f["action"] == "auto_fixed"
        )
        flagged = sum(
            1 for f in self.state.fix_log
            if f["action"] == "flagged_for_review"
        )

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

        auto_fixed = sum(
            1 for f in self.state.fix_log
            if f["action"] == "auto_fixed"
        )
        flagged = sum(
            1 for f in self.state.fix_log
            if f["action"] == "flagged_for_review"
        )

        try:
            narrative = self.call_llm(
                "You are a data quality analyst. Given these fix actions, "
                "write a concise summary (3-5 sentences) of what was "
                "remediated and what was flagged for human review.",
                f"Fix actions:\n{fix_summary}",
            ).strip()
        except Exception as e:
            self.log("error", str(e))
            narrative = (
                f"{auto_fixed} issues auto-remediated, "
                f"{flagged} issues flagged for human review."
            )

        self.state.remediation_plan = self.state.fix_log
        self.log("reply", narrative)
