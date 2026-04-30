"""LookupImputationStrategy (B2 ordering) — fills missing target-column
cells from a learned ``mapping_source -> target`` dictionary built on the
clean rows of the same dataframe. Now runs BEFORE ``MissingValuesStrategy``
so cells that the placeholder pass converted to NULL become eligible for
lookup imputation; only the residual NULLs flow into median / mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pandas as pd

from state.issues import Issue
from tools import apply_lookup_imputation, build_column_lookup

if TYPE_CHECKING:
    from agents_demo.remediation_agent import RemediationAgent


class LookupImputationStrategy:
    name: ClassVar[str] = "lookup_imputation"
    applies_to: ClassVar[frozenset[str]] = frozenset({"lookup_imputability"})

    def apply(
        self,
        df: pd.DataFrame,
        issues_by_type: dict[str, list[Issue]],
        fp: dict[str, Any],
        agent: RemediationAgent,
    ) -> None:
        for issue in issues_by_type.get("lookup_imputability", []):
            tgt = issue.get("column", "")
            src = issue.get("mapping_source", "")
            if not tgt or not src or tgt not in df.columns or src not in df.columns:
                continue
            lookup = build_column_lookup(df, src, tgt)
            if not lookup:
                continue
            filled = apply_lookup_imputation(df, src, tgt, lookup)
            if filled > 0:
                agent.log_fix(
                    issue,
                    "auto_fixed",
                    f"Imputed {filled} missing '{tgt}' values from '{src}' "
                    f"via learned mapping ({len(lookup)} unique mappings)",
                    filled,
                )
            else:
                agent.log("act", f"Lookup imputation for '{tgt}' <- '{src}': 0 rows filled")
