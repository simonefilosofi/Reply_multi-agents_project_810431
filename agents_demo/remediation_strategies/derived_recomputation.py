"""DerivedRecomputationStrategy -- after outlier capping has modified one or
more base numeric columns.

This strategy detects derived-named columns (profit, margin, net, total, balance, ...)
that approximately satisfy ``c == a - b`` in the *raw* data, where ``a`` was capped and ``b`` was
NOT, and recomputes ``c = a_clean - b_clean`` so additive consistency is
restored on the cleaned dataframe.

Only columns whose names contain a derived-keyword token are eligible -- the
guard prevents the algorithm from "correcting" a base measurement using
arithmetic from a derived one. The strategy declares no ``applies_to`` issue
type because it consumes the fix log produced by earlier strategies, not a
detector-emitted issue; ``RemediationAgent`` invokes it explicitly at the
end of ``STRATEGY_ORDER``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state_demo.issues import Issue

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


_DERIVED_KEYWORDS: frozenset[str] = frozenset(
    {
        "profit",
        "margin",
        "net",
        "total",
        "balance",
        "diff",
        "delta",
        "change",
        "result",
        "gain",
        "loss",
        "surplus",
        "deficit",
        "yield",
        "return",
    }
)


def _looks_derived(col_name: str) -> bool:
    lower = col_name.lower()
    return any(kw in lower for kw in _DERIVED_KEYWORDS)


class DerivedRecomputationStrategy:
    name: ClassVar[str] = "derived_recomputation"
    applies_to: ClassVar[frozenset[str]] = frozenset()

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        df_raw = agent.state.df_raw
        capped_cols = {
            f["column"]
            for f in agent.state.fix_log
            if f["issue_type"] == "outliers" and f["action"] == "auto_fixed"
        }
        if not capped_cols:
            return

        num_cols = [
            col
            for col in df.columns
            if col in df_raw.columns
            and pd.to_numeric(df_raw[col], errors="coerce").notna().mean() > 0.80
        ]
        if len(num_cols) < 3:
            return

        recomputed: set[str] = set()
        min_rows = max(10, int(len(df) * 0.50))

        for col_c in num_cols:
            if not _looks_derived(col_c):
                continue
            if col_c in capped_cols or col_c in recomputed:
                continue
            c_raw = pd.to_numeric(df_raw[col_c], errors="coerce")

            for col_a in capped_cols:
                if col_a not in num_cols or col_a == col_c:
                    continue
                a_raw = pd.to_numeric(df_raw[col_a], errors="coerce")

                for col_b in num_cols:
                    if col_b in capped_cols or col_b in (col_a, col_c):
                        continue
                    b_raw = pd.to_numeric(df_raw[col_b], errors="coerce")
                    both_valid = c_raw.notna() & a_raw.notna() & b_raw.notna()
                    if int(both_valid.sum()) < min_rows:
                        continue

                    diff = a_raw[both_valid] - b_raw[both_valid]
                    c_sub = c_raw[both_valid]
                    denom = c_sub.abs().clip(lower=1e-9)
                    rel_err = (c_sub - diff).abs() / denom

                    if rel_err.mean() < 0.01 and (rel_err < 0.05).mean() > 0.95:
                        a_clean = pd.to_numeric(df[col_a], errors="coerce")
                        b_clean = pd.to_numeric(df[col_b], errors="coerce")
                        recomputed_vals = a_clean - b_clean
                        n_updated = int(recomputed_vals.notna().sum())
                        df[col_c] = recomputed_vals
                        recomputed.add(col_c)
                        agent.log_fix(
                            {
                                "type": "derived_column_recomputation",
                                "column": col_c,
                            },
                            "auto_fixed",
                            f"Recomputed '{col_c}' = '{col_a}' - '{col_b}' "
                            f"after outlier capping to restore arithmetic "
                            f"consistency ({n_updated} rows updated)",
                            n_updated,
                        )
                        agent.log(
                            "act",
                            f"Recomputed derived column '{col_c}' = '{col_a}' - '{col_b}'",
                        )
                        break
                if col_c in recomputed:
                    break
