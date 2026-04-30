"""End-to-end regression test for B2 (lookup imputation must run before
median / mode imputation).

Constructs a column that contains both placeholder cells and missing cells
where each missing cell can be inferred from a sibling column via a learned
mapping. After remediation:

* the placeholder is converted to NULL by ``PlaceholderStrategy``;
* the lookup-imputable cells (the original-NaN one and the placeholder-now-NULL
  one) are filled by ``LookupImputationStrategy`` with the looked-up value;
* ``MissingValuesStrategy`` does NOT overwrite those cells with the column
  median, because it recomputes ``is_missing`` after the lookup pass and
  finds zero residual NULLs.

The strategy registry order encodes the invariant; the assertions below
fail loudly if the order is ever swapped back.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from agents_demo.remediation_agent import RemediationAgent
from state.issues import (
    LookupImputabilityIssue,
    MissingValuesIssue,
    PlaceholderValuesIssue,
)
from state.pipeline_state import PipelineState


def test_lookup_imputation_runs_before_median_imputation(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame(
        {
            "region_code": [
                "RM",
                "RM",
                "RM",
                "RM",
                "MI",
                "MI",
                "MI",
                "MI",
                "RM",
                "MI",
            ],
            "region_population": [
                "2800000",
                "2800000",
                "2800000",
                "2810000",
                "1400000",
                "1400000",
                "1400000",
                "1410000",
                "n.d.",
                None,
            ],
        }
    )
    state.df_raw = df
    state.dataset_fingerprint = {
        "domain": "test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": ["region_population"],
        "categorical_columns": ["region_code"],
        "date_columns": [],
        "sparse_columns": [],
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    state.prioritized_issues = [
        PlaceholderValuesIssue(
            column="region_population",
            detail="1 placeholder cell",
            severity="medium",
            count=1,
        ),
        LookupImputabilityIssue(
            column="region_population",
            mapping_source="region_code",
            detail="population inferable from region_code",
            severity="medium",
            n_imputable=2,
        ),
        MissingValuesIssue(
            column="region_population",
            detail="2 missing values",
            severity="low",
            missing_count=2,
            total=10,
        ),
    ]
    monkeypatch_llm["call_llm_json"] = {"gap_issues": []}

    RemediationAgent(state).run("remediation")

    df_clean = state.df_cleaned
    assert df_clean is not None

    cleaned_pop = pd.to_numeric(df_clean["region_population"], errors="coerce")
    assert cleaned_pop.notna().all(), "remediation must leave no missing population cells"

    learned_median = cleaned_pop.median()
    assert cleaned_pop.iloc[8] == 2800000.0, (
        "B2 invariant: placeholder cell with code='RM' must be lookup-imputed "
        f"to 2800000, not to median {learned_median}"
    )
    assert cleaned_pop.iloc[9] == 1400000.0, (
        "B2 invariant: missing cell with code='MI' must be lookup-imputed "
        f"to 1400000, not to median {learned_median}"
    )
    assert cleaned_pop.iloc[8] != learned_median
    assert cleaned_pop.iloc[9] != learned_median

    actions = [(f["issue_type"], f["action"]) for f in state.fix_log]
    placeholder_idx = next(
        i for i, a in enumerate(actions) if a == ("placeholder_values", "auto_fixed")
    )
    lookup_idx = next(
        i for i, a in enumerate(actions) if a == ("lookup_imputability", "auto_fixed")
    )
    assert placeholder_idx < lookup_idx, (
        "PlaceholderStrategy must log before LookupImputationStrategy "
        "so cells nulled out can be lookup-imputed"
    )

    median_entries = [
        f
        for f in state.fix_log
        if f["issue_type"] == "missing_values" and f["action"] == "auto_fixed"
    ]
    assert not median_entries, (
        "MissingValuesStrategy must not auto-fix anything: lookup imputation "
        "filled every NULL before it ran"
    )

    lookup_entry = next(f for f in state.fix_log if f["issue_type"] == "lookup_imputability")
    assert lookup_entry["rows_affected"] == 2, (
        "LookupImputationStrategy must report 2 rows filled "
        "(the original-NaN cell plus the placeholder-now-NULL cell)"
    )
