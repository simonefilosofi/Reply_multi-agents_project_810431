"""CurrencySymbolStrategy (A3 closure) -- strips currency symbols from numeric columns.

Removes leading currency markers (euro, dollar, pound, ...) via
``tools.fix_currency_symbols_in_numeric``. Runs BEFORE ``CommaDecimalStrategy``
because comma-decimal recognition needs the leading symbol gone first
(``'EUR 1.234,56'`` -> ``'1.234,56'`` -> ``1234.56``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue
from tools import fix_currency_symbols_in_numeric

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class CurrencySymbolStrategy:
    name: ClassVar[str] = "currency_symbol"
    applies_to: ClassVar[frozenset[str]] = frozenset({"currency_symbol_in_numeric"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("currency_symbol_in_numeric", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            changed = fix_currency_symbols_in_numeric(df, col)
            if changed > 0:
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Stripped currency symbols from {changed} values in numeric column '{col}'",
                    changed,
                )
            else:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    f"Currency symbols flagged on '{col}' but no values "
                    f"could be safely stripped — manual review",
                    0,
                )
