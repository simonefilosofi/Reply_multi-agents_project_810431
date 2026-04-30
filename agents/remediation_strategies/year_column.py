"""YearColumnStrategy — merges ``year_format_inconsistency`` and
``ambiguous_year_format`` into a single ``tools.fix_year_column`` pass per
column (strips trailing noise, expands 2-digit centuries from the dominant
year in the column).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import fix_year_column

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class YearColumnStrategy:
    name: ClassVar[str] = "year_column"
    applies_to: ClassVar[frozenset[str]] = frozenset(
        {"year_format_inconsistency", "ambiguous_year_format"}
    )

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        seen: set[str] = set()
        ordered_issues = issues_by_type.get("year_format_inconsistency", []) + issues_by_type.get(
            "ambiguous_year_format", []
        )
        for issue in ordered_issues:
            col = issue.get("column", "")
            if not col or col in seen or col not in df.columns:
                continue
            seen.add(col)
            changed = fix_year_column(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Normalised {changed} year values to 4-digit integers "
                f"(stripped trailing noise, expanded 2-digit years)",
                changed,
            )
