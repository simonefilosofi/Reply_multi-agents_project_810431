"""PeriodFormatStrategy — normalises mixed YYYYMM / YYYY-MM / YYYY.MM
period codes to canonical YYYYMM via ``tools.normalize_period_column``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import normalize_period_column

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class PeriodFormatStrategy:
    name: ClassVar[str] = "period_format"
    applies_to: ClassVar[frozenset[str]] = frozenset({"period_format_inconsistency"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("period_format_inconsistency", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            normalised, nulled = normalize_period_column(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Normalised {normalised} period values to canonical "
                f"YYYYMM format; {nulled} unparseable values set to NULL",
                normalised + nulled,
            )
