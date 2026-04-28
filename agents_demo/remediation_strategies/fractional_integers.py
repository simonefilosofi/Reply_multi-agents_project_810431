"""FractionalIntegersStrategy -- nulls non-trivial fractional values.

Targets columns the profiler classified as integer-typed and applies
``tools.fix_fractional_integers``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import fix_fractional_integers

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class FractionalIntegersStrategy:
    name: ClassVar[str] = "fractional_integers"
    applies_to: ClassVar[frozenset[str]] = frozenset({"fractional_integers"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("fractional_integers", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            nulled = fix_fractional_integers(df, col)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Nulled {nulled} values with non-trivial fractional parts in integer column",
                nulled,
            )
