"""MissingValuesStrategy — fills residual NULLs left over after
``PlaceholderStrategy`` and ``LookupImputationStrategy`` have run. The
NULL mask is recomputed at apply-time so cells the lookup pass just filled
do NOT get overwritten with median / mode (B2 ordering invariant).

Per-column dispatch:
  - id / date columns: flag for review (auto-imputation would corrupt keys
    or hide ground-truth absence).
  - numerical columns at high / medium severity: flag (median imputation
    biases summary statistics on heavy missingness).
  - numerical columns at low severity: median imputation.
  - categorical columns: mode imputation guarded by ``fill_missing_categorical``.
  - binary flag columns (<= 2 distinct values): flag (preserves event rate).
  - everything else: ask the LLM for a strategy via ``RemediationAgent.ask_llm_strategy``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.helpers import missing_mask
from state.issues import Issue
from tools import fill_missing_categorical, fill_missing_numerical

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class MissingValuesStrategy:
    name: ClassVar[str] = "missing_values"
    applies_to: ClassVar[frozenset[str]] = frozenset({"missing_values"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("missing_values", []):
            self._fix_one(df, issue, fp, agent)

    def _fix_one(
        self,
        df: pd.DataFrame,
        issue: Issue,
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        col = issue.get("column", "")
        if not col or col not in df.columns:
            return
        is_missing = missing_mask(df[col])
        rows_affected = int(is_missing.sum())
        if rows_affected == 0:
            return

        num_cols = set(fp.get("numerical_columns", []))
        date_cols = set(fp.get("date_columns", []))
        cat_cols = set(fp.get("categorical_columns", []))
        severity = issue.get("severity", "low")

        valid_vals = df.loc[~is_missing, col].dropna()
        if valid_vals.astype(str).str.strip().nunique() <= 2:
            agent.log_fix(
                issue,
                "flagged_for_review",
                f"Binary flag column with {rows_affected} missing values "
                f"-- auto-imputation suppressed to preserve flag distribution; "
                f"requires domain review",
                rows_affected,
            )
            return

        if col in num_cols:
            if severity in ("high", "medium"):
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    f"Numerical column with {rows_affected} missing values "
                    f"(severity={severity}): median imputation suppressed to "
                    f"prevent statistical bias -- requires domain review",
                    rows_affected,
                )
                return
            success, detail = fill_missing_numerical(df, col, is_missing)
            action = "auto_fixed" if success else "flagged_for_review"
            agent.log_fix(issue, action, detail, rows_affected)
            return

        if col in date_cols:
            agent.log_fix(
                issue,
                "flagged_for_review",
                f"Date column with {rows_affected} missing values "
                f"-- requires domain knowledge to impute",
                rows_affected,
            )
            return

        if col in cat_cols:
            success, detail = fill_missing_categorical(df, col, is_missing, severity)
            action = "auto_fixed" if success else "flagged_for_review"
            agent.log_fix(issue, action, detail, rows_affected)
            return

        strategy = agent.ask_llm_strategy(col, issue, fp)
        if strategy == "median":
            success, detail = fill_missing_numerical(df, col, is_missing)
            action = "auto_fixed" if success else "flagged_for_review"
            agent.log_fix(issue, action, detail, rows_affected)
            return
        if strategy == "mode":
            success, detail = fill_missing_categorical(df, col, is_missing, severity)
            action = "auto_fixed" if success else "flagged_for_review"
            agent.log_fix(issue, action, detail, rows_affected)
            return
        agent.log_fix(
            issue,
            "flagged_for_review",
            f"Unclassified column with {rows_affected} missing values -- flagged for human review",
            rows_affected,
        )
