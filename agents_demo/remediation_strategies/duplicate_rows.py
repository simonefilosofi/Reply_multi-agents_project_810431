"""DuplicateRowsStrategy -- single-shot row deduplication.

Keys on every column and keeps the first occurrence. Runs once regardless
of how many ``duplicate_rows`` issue rows the detector emitted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import remove_duplicate_rows

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class DuplicateRowsStrategy:
    name: ClassVar[str] = "duplicate_rows"
    applies_to: ClassVar[frozenset[str]] = frozenset({"duplicate_rows"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        if not issues_by_type.get("duplicate_rows"):
            return
        removed = remove_duplicate_rows(df)
        df.reset_index(drop=True, inplace=True)
        agent.log_fix(
            {"type": "duplicate_rows", "column": "_rows_"},
            "auto_fixed",
            f"Removed {removed} duplicate rows (kept first occurrence)",
            removed,
        )
