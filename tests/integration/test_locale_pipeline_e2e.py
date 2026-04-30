"""End-to-end regression test for A3 (Italian-locale auto-fix dispatch).

Feeds a column whose cells look like ``'€ 1.234,56'`` (currency symbol +
comma-decimal) into the full ``RemediationAgent``. The strategy registry is
expected to:

1. ``CurrencySymbolStrategy`` strips the leading euro symbol and surrounding
   whitespace, so the cell becomes ``'1.234,56'``.
2. ``CommaDecimalStrategy`` recognises the IT_DECIMAL_PATTERN match and
   rewrites the cell to canonical ``'1234.56'``.
3. ``MixedTypeStrategy`` coerces the now-clean string column to ``float64``
   via ``pd.to_numeric``.

The cleaned dataframe must be a numeric column with the original euro
amounts intact as floats (1234.56, 2500.00, ...). If the locale strategies
ever stop running, or run in the wrong order (comma-decimal before currency
strip), the column ends up entirely NaN after ``MixedTypeStrategy`` and the
final assertion catches the regression.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from agents_demo.remediation_agent import RemediationAgent
from state.issues import (
    CommaDecimalFormatIssue,
    CurrencySymbolInNumericIssue,
    MixedTypeIssue,
)
from state.pipeline_state import PipelineState


def test_currency_then_comma_decimal_then_numeric_coercion(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame(
        {
            "amount": [
                "€ 1.234,56",
                "€ 2.500,00",
                "€ 999,99",
                "€ 100,00",
                "€ 1.000,00",
                "€ 1.500,00",
                "€ 750,00",
                "€ 50,00",
                "€ 200,00",
                "€ 1.234,56",
            ]
        }
    )
    state.df_raw = df
    state.dataset_fingerprint = {
        "domain": "test",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": ["amount"],
        "categorical_columns": [],
        "date_columns": [],
        "sparse_columns": [],
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    state.prioritized_issues = [
        CurrencySymbolInNumericIssue(
            column="amount",
            detail="euro symbols in numeric column",
            severity="medium",
            currency_examples=["€"],
            count=10,
        ),
        CommaDecimalFormatIssue(
            column="amount",
            detail="Italian comma-decimal format",
            severity="medium",
            count=10,
        ),
        MixedTypeIssue(
            column="amount",
            detail="non-numeric strings in numeric column",
            severity="medium",
            numeric_count=0,
            non_numeric_count=10,
        ),
    ]
    monkeypatch_llm["call_llm_json"] = {"gap_issues": []}

    RemediationAgent(state).run("remediation")

    df_clean = state.df_cleaned
    assert df_clean is not None
    cleaned = df_clean["amount"]

    assert pd.api.types.is_numeric_dtype(cleaned), (
        f"locale pipeline must yield a numeric column, got dtype={cleaned.dtype}"
    )
    assert cleaned.notna().all(), "every cleaned amount must coerce to a real float"

    expected = [
        1234.56,
        2500.00,
        999.99,
        100.00,
        1000.00,
        1500.00,
        750.00,
        50.00,
        200.00,
        1234.56,
    ]
    for actual, want in zip(cleaned.tolist(), expected, strict=True):
        assert actual == pytest.approx(want), f"got {actual} expected {want}"

    fix_types = {f["issue_type"] for f in state.fix_log}
    assert "currency_symbol_in_numeric" in fix_types, (
        "CurrencySymbolStrategy must log a fix entry for the issue"
    )
    assert ("comma_decimal_format", "auto_fixed") in {
        (f["issue_type"], f["action"]) for f in state.fix_log
    }, "CommaDecimalStrategy must auto-fix once the currency strip exposes the IT pattern"
    assert ("mixed_type", "auto_fixed") in {
        (f["issue_type"], f["action"]) for f in state.fix_log
    }, "MixedTypeStrategy must auto-fix the now-clean numeric strings"
