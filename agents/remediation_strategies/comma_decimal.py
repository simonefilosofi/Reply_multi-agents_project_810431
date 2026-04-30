"""CommaDecimalStrategy (A3 closure) -- normalises Italian comma-decimal strings.

Converts cells like ``'1.234,56'`` to canonical ``'1234.56'`` via
``tools.fix_comma_decimal_format``. Runs AFTER ``CurrencySymbolStrategy`` so
the leading symbol is already stripped, and BEFORE ``MixedTypeStrategy`` so
the resulting numeric strings coerce cleanly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import fix_comma_decimal_format

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class CommaDecimalStrategy:
    name: ClassVar[str] = "comma_decimal"
    applies_to: ClassVar[frozenset[str]] = frozenset({"comma_decimal_format"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("comma_decimal_format", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            changed = fix_comma_decimal_format(df, col)
            if changed > 0:
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Converted {changed} Italian comma-decimal values "
                    f"to canonical dot-decimal format on '{col}'",
                    changed,
                )
            else:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    f"Comma-decimal flagged on '{col}' but no values "
                    f"could be safely converted — manual review",
                    0,
                )
