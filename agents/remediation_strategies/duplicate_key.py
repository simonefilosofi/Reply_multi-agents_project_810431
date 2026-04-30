"""DuplicateKeyStrategy -- removes rows with colliding id-column keys.

Drops rows that share the same value(s) on the profiler-declared id columns
(kept first occurrence). Non-id-column key collisions are flagged for domain
review because dropping them would silently lose business information.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class DuplicateKeyStrategy:
    name: ClassVar[str] = "duplicate_key"
    applies_to: ClassVar[frozenset[str]] = frozenset({"duplicate_key"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        id_cols = set(fp.get("id_columns", []))
        for issue in issues_by_type.get("duplicate_key", []):
            raw = issue.get("column", "")
            key_cols = [c.strip() for c in raw.split(",") if c.strip() in df.columns]
            if not key_cols:
                continue
            id_key_cols = [c for c in key_cols if c in id_cols]
            if id_key_cols:
                before = len(df)
                df.drop_duplicates(subset=key_cols, keep="first", inplace=True)
                df.reset_index(drop=True, inplace=True)
                removed = before - len(df)
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Removed {removed} rows with duplicate primary key "
                    f"[{raw}] (kept first occurrence per key)",
                    removed,
                )
            else:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    "Rows share key values but key is not on profiler "
                    "id_columns -- requires manual review",
                    0,
                )
