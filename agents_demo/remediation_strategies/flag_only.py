"""FlagOnlyStrategy -- catch-all that records issue types which the pipeline
cannot safely auto-remediate. Each handled type gets a canned human-readable
description so the report can render a coherent flagged-for-review section.

A3 closure: ``currency_symbol_in_numeric`` and ``comma_decimal_format`` are
NOT listed here -- they are now auto-fixed by ``CurrencySymbolStrategy`` and
``CommaDecimalStrategy`` respectively. They will only ever reach this
strategy if the locale fix tool returned 0 changes, in which case those
strategies emit their own flagged_for_review entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


_FLAG_TYPES: tuple[str, ...] = (
    "sparse_column",
    "date_order",
    "rare_categories",
    "conditional_completeness",
    "cross_column_mismatch",
    "domain_negative_values",
    "nd_placeholder_in_numeric",
    "ambiguous_year_format",
    "invalid_year_value",
)


_DESCRIPTIONS: dict[str, str] = {
    "sparse_column": "Recommended for removal -- requires domain review",
    "duplicate_columns": "Columns may contain redundant data -- review for removal",
    "duplicate_key": "Rows share key values but differ elsewhere -- manual review needed",
    "date_order": "Cannot auto-fix date ordering without domain knowledge",
    "rare_categories": "Suggest grouping into 'Other' -- requires domain approval",
    "conditional_completeness": "Related column has gaps -- requires domain knowledge",
    "cross_column_mismatch": "Column value disagreement -- requires domain knowledge to resolve",
    "domain_negative_values": "Negative values in non-negative column -- requires manual review",
    "nd_placeholder_in_numeric": "N.D. placeholders in numeric column -- should be proper NULLs",
    "format_pattern_violation": "Values violating format pattern but no pattern stored "
    "-- flagged for review",
    "ambiguous_year_format": "2-digit year values -- century expanded automatically "
    "from dominant year in column",
    "invalid_year_value": "Year values outside [1900-2099] "
    "-- requires domain review before correction",
    "year_format_inconsistency": "Dirty year strings -- cleaned automatically "
    "(trailing non-digit noise stripped)",
}


class FlagOnlyStrategy:
    name: ClassVar[str] = "flag_only"
    applies_to: ClassVar[frozenset[str]] = frozenset(_FLAG_TYPES)

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for flag_type in _FLAG_TYPES:
            for issue in issues_by_type.get(flag_type, []):
                col = issue.get("column", "")
                if col and col not in df.columns:
                    continue
                desc = _DESCRIPTIONS.get(flag_type, "Flagged for human review")
                agent.log_fix(issue, "flagged_for_review", desc, 0)
