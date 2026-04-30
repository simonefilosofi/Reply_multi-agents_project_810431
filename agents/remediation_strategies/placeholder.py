"""PlaceholderStrategy — replaces sentinel placeholders (e.g. 'n.d.',
'da verificare', '...') with NULL using the combined exact-match plus regex
detector ``tools._is_placeholder_series``. Runs early so cells become eligible
for downstream lookup imputation and median/mode filling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import _is_placeholder_series

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class PlaceholderStrategy:
    name: ClassVar[str] = "placeholder"
    applies_to: ClassVar[frozenset[str]] = frozenset({"placeholder_values"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("placeholder_values", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            placeholder_mask = _is_placeholder_series(df[col])
            count = int(placeholder_mask.sum())
            if count > 0:
                df.loc[placeholder_mask, col] = None
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Replaced {count} placeholder cells with NULL",
                    count,
                )
