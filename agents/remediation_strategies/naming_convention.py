"""NamingConventionStrategy -- rewrites column names to snake_case.

Uses ``tools.fix_column_naming``. Runs AFTER ``DuplicateColumnsStrategy`` so
the original names recorded by ``DuplicateAgent`` are still present when the
duplicate drop happens; this strategy then cleans up only the survivors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import fix_column_naming

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class NamingConventionStrategy:
    name: ClassVar[str] = "naming_convention"
    applies_to: ClassVar[frozenset[str]] = frozenset({"naming_convention"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("naming_convention", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            old, new = fix_column_naming(df, col)
            if new != old:
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Renamed '{old}' -> '{new}'",
                    0,
                    old=old,
                    new=new,
                )
