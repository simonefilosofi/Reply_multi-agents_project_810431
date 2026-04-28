"""CaseInconsistencyStrategy -- normalises mixed-case string variants.

Collapses ('milano', 'Milano', 'MILANO' -> 'Milano') to the most frequent
casing variant via ``tools.normalize_case``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import normalize_case

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class CaseInconsistencyStrategy:
    name: ClassVar[str] = "case_inconsistency"
    applies_to: ClassVar[frozenset[str]] = frozenset({"case_inconsistency"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("case_inconsistency", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            changed = normalize_case(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Normalized {changed} values to most frequent casing variant",
                changed,
            )
