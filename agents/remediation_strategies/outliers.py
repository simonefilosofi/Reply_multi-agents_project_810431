"""OutlierStrategy — caps Tukey 3xIQR outliers in numeric columns. Skips
ID/key columns, profiler-classified categoricals, and power-law / heavily
skewed distributions whose tails carry signal rather than noise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import cap_outliers

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class OutlierStrategy:
    name: ClassVar[str] = "outliers"
    applies_to: ClassVar[frozenset[str]] = frozenset({"outliers"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        id_cols = set(fp.get("id_columns", []))
        cat_cols = set(fp.get("categorical_columns", []))
        for issue in issues_by_type.get("outliers", []):
            col = issue.get("column", "")
            if not col or col not in df.columns:
                continue
            if col in id_cols:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    "Outlier in ID/key column -- "
                    "capping would corrupt semantics, requires manual review",
                    0,
                )
                continue
            if col in cat_cols:
                agent.log_fix(
                    issue,
                    "flagged_for_review",
                    "Column classified as categorical (codes/enums) -- "
                    "outlier capping suppressed to preserve category integrity",
                    0,
                )
                continue
            raw_numeric = pd.to_numeric(agent.state.df_raw[col], errors="coerce").dropna()
            if len(raw_numeric) > 3:
                skewness = float(raw_numeric.skew())
                q1, q3 = raw_numeric.quantile(0.25), raw_numeric.quantile(0.75)
                iqr = q3 - q1
                cap_rate = (
                    ((raw_numeric < q1 - 3 * iqr) | (raw_numeric > q3 + 3 * iqr)).mean()
                    if iqr > 0
                    else 0.0
                )
                if abs(skewness) > 2.0 or cap_rate > 0.05:
                    agent.log_fix(
                        issue,
                        "flagged_for_review",
                        f"Skewed distribution (skewness={skewness:.2f}, "
                        f"{cap_rate:.1%} of values beyond 3xIQR fence) -- "
                        f"capping suppressed to preserve power-law structure; "
                        f"use log-transform or domain-specific bounds instead",
                        0,
                    )
                    continue
            lower, upper, count = cap_outliers(df, col, agent.state.df_raw[col])
            if count > 0:
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Capped {count} outliers to [{lower:.2f}, {upper:.2f}] (3xIQR fence)",
                    count,
                )
