"""FloatPrecisionStrategy -- rounds floating-point noise to two decimals.

Trims artefacts like ``1.000000001 -> 1.0`` via
``tools.round_float_precision``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import round_float_precision

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class FloatPrecisionStrategy:
    name: ClassVar[str] = "float_precision"
    applies_to: ClassVar[frozenset[str]] = frozenset({"float_precision_noise"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("float_precision_noise", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            changed = round_float_precision(df, col, decimals=2)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Rounded {changed} values to 2 decimal places to remove floating-point noise",
                changed,
            )
