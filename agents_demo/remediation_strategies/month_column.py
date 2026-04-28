"""MonthColumnStrategy — merges ``month_format_inconsistency`` and
``special_month_code`` into a single ``tools.fix_month_column`` pass per
column so a column flagged twice gets corrected exactly once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import fix_month_column

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class MonthColumnStrategy:
    name: ClassVar[str] = "month_column"
    applies_to: ClassVar[frozenset[str]] = frozenset(
        {"month_format_inconsistency", "special_month_code"}
    )

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        seen: set[str] = set()
        ordered_issues = issues_by_type.get("month_format_inconsistency", []) + issues_by_type.get(
            "special_month_code", []
        )
        for issue in ordered_issues:
            col = issue.get("column", "")
            if not col or col in seen or col not in df.columns:
                continue
            seen.add(col)
            changed = fix_month_column(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Normalised {changed} month values to integers 1-12 "
                f"(converted text names, nulled special codes)",
                changed,
            )
