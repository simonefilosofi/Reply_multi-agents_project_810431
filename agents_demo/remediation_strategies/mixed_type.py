"""MixedTypeStrategy -- coerces profiler-numeric columns to ``pd.to_numeric``.

Non-coercible values become NaN. Runs AFTER the locale strategies so
currency symbols and Italian decimals do not bleed into ``coerced`` counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import fix_mixed_type

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class MixedTypeStrategy:
    name: ClassVar[str] = "mixed_type"
    applies_to: ClassVar[frozenset[str]] = frozenset({"mixed_type"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("mixed_type", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            coerced = fix_mixed_type(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Coerced to numeric -- {coerced} non-numeric values became NaN",
                coerced,
            )
