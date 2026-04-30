"""FormatPatternStrategy (B1 closure) — nulls cells that violate an
LLM-inferred regex pattern stored on the typed
:class:`FormatPatternViolationIssue`. ID / suggested-key columns are flagged
for manual review instead, because an incorrect inferred pattern would
destroy the primary key. Reads ``issue.pattern`` directly via the typed
field accessor (no string-keyed fallback).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import FormatPatternViolationIssue, Issue
from tools import null_pattern_violations

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class FormatPatternStrategy:
    name: ClassVar[str] = "format_pattern"
    applies_to: ClassVar[frozenset[str]] = frozenset({"format_pattern_violation"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        id_cols = set(fp.get("id_columns", []))
        key_cols = set(fp.get("suggested_key_columns", []))
        for issue in issues_by_type.get("format_pattern_violation", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            if col in id_cols or col in key_cols:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    f"Format pattern violation in ID/key column "
                    f"'{col}' -- auto-nulling suppressed to preserve "
                    f"primary key integrity",
                    0,
                )
                continue
            pattern = (
                issue.pattern
                if isinstance(issue, FormatPatternViolationIssue)
                else issue.get("pattern", "")
            )
            if not pattern:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    "Format pattern violation but no pattern stored -- flagged for review",
                    0,
                )
                continue
            nulled = null_pattern_violations(df, col, pattern)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Nulled {nulled} values violating expected format pattern",
                nulled,
            )
