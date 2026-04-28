"""FormatInconsistencyStrategy -- standardises mixed date-string formats.

Collapses a column to a single canonical representation via
``tools.standardize_date_format``. The tool returns its own (action, detail)
tuple so the strategy just relays it to ``log_fix``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import standardize_date_format

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class FormatInconsistencyStrategy:
    name: ClassVar[str] = "format_inconsistency"
    applies_to: ClassVar[frozenset[str]] = frozenset({"format_inconsistency"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("format_inconsistency", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            action, detail = standardize_date_format(df, col)
            rows_affected = 0 if action == "flagged_for_review" else 1
            agent.log_fix(issue, action, detail, rows_affected)
