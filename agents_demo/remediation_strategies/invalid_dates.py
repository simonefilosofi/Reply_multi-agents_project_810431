"""InvalidDatesStrategy -- re-parses date columns flagged by SchemaAgent.

Uses ``tools.fix_invalid_dates``, an Italian-month-aware best-effort parser
with multi-format fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import fix_invalid_dates

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class InvalidDatesStrategy:
    name: ClassVar[str] = "invalid_dates"
    applies_to: ClassVar[frozenset[str]] = frozenset({"invalid_dates"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("invalid_dates", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            method, valid = fix_invalid_dates(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Re-parsed dates ({method}) -- {valid}/{len(df)} values parsed successfully",
                valid,
            )
