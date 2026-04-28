"""DuplicateColumnsStrategy -- drops near-duplicate column pairs.

Removes one of two columns flagged as near-duplicates by ``DuplicateAgent``,
after a content-domain Jaccard guard to avoid dropping complementary columns
(e.g. numeric codes vs. text descriptions). Placeholder values (n.d., -, ?)
are excluded from the similarity computation so shared sentinels don't
inflate Jaccard.

The strategy MUST run before ``NamingConventionStrategy`` so the original
column names that DuplicateAgent recorded still exist in ``df``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.constants import PLACEHOLDERS
from state_demo.issues import Issue
from tools import pick_duplicate_column_to_drop

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


def _content_set(df: pd.DataFrame, col: str) -> set[str]:
    vals = df[col].dropna().astype(str).str.strip()
    return {
        v
        for v in vals
        if v and v.lower() not in PLACEHOLDERS and not all(c in r"-./?#\/ " for c in v)
    }


class DuplicateColumnsStrategy:
    name: ClassVar[str] = "duplicate_columns"
    applies_to: ClassVar[frozenset[str]] = frozenset({"duplicate_columns"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        dropped: set[str] = set()
        for issue in issues_by_type.get("duplicate_columns", []):
            raw = issue.get("column", "")
            parts = [c.strip() for c in raw.split("/")]
            if len(parts) != 2:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    "Duplicate-columns issue did not encode a 'col_a/col_b' pair "
                    "-- flagged for review",
                    0,
                )
                continue
            col_a, col_b = parts
            if col_a not in df.columns or col_b not in df.columns:
                continue
            set_a = _content_set(df, col_a)
            set_b = _content_set(df, col_b)
            if set_a and set_b:
                jaccard = len(set_a & set_b) / len(set_a | set_b)
                if jaccard < 0.20:
                    agent.log_fix(
                        issue,
                        "flagged_for_review",
                        f"Skipped drop of '{col_a}'/'{col_b}': "
                        f"value-domain Jaccard={jaccard:.2f} -- "
                        f"columns are complementary",
                        0,
                    )
                    continue
            to_drop = pick_duplicate_column_to_drop(col_a, col_b)
            to_keep = col_b if to_drop == col_a else col_a
            if to_drop in dropped:
                continue
            df.drop(columns=[to_drop], inplace=True)
            dropped.add(to_drop)
            agent.log_fix(
                issue,
                "auto_fixed",
                f"Dropped duplicate column '{to_drop}' (kept '{to_keep}')",
                0,
            )
