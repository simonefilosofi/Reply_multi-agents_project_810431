"""Tests for tools.py — deterministic detectors and fixers.

Mix of currently-passing happy-path coverage and ``xfail``-marked acceptance
tests for the audit findings that Step 6 will close (B1, A3, H5).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from state_demo.constants import PLACEHOLDERS
from tools import (
    apply_lookup_imputation,
    check_format_pattern,
    check_naming_conventions,
    compute_completeness,
    detect_duplicate_rows,
    detect_outliers,
    detect_rare_categories,
    normalize_period_column,
    statistical_fingerprint,
)


def _legacy_apply_lookup_imputation(
    df: pd.DataFrame, col_source: str, col_target: str, lookup: dict[str, Any]
) -> int:
    """Row-by-row legacy implementation used as the parity reference for H5.

    Removed from the test suite once Step 6 lands the vectorised version in
    tools.py and the regression check has been observed to pass.
    """
    if not lookup or col_source not in df.columns or col_target not in df.columns:
        return 0
    pl = {p.lower() for p in PLACEHOLDERS} | {""}
    tgt_missing = df[col_target].isna() | df[col_target].astype(str).str.strip().str.lower().isin(
        pl
    )
    src_present = df[col_source].notna() & ~df[col_source].astype(str).str.strip().str.lower().isin(
        pl
    )
    imputable = df.index[tgt_missing & src_present]
    count = 0
    for idx in imputable:
        imputed_val = lookup.get(str(df.at[idx, col_source]))
        if imputed_val is not None:
            df.at[idx, col_target] = imputed_val
            count += 1
    return count


def test_statistical_fingerprint_partitions_columns(clean_pa_df: pd.DataFrame) -> None:
    """imposta/spesa must bucket as numerical and rata (YYYYMM) as categorical."""
    fp = statistical_fingerprint(clean_pa_df)
    assert "imposta" in fp.get("numerical_columns", [])
    assert "spesa" in fp.get("numerical_columns", [])
    assert "rata" in fp.get("categorical_columns", [])
    assert "imposta" not in fp.get("date_columns", [])
    assert "spesa" not in fp.get("date_columns", [])


def test_compute_completeness_clean_dataset_is_full(
    clean_pa_df: pd.DataFrame,
) -> None:
    """A clean dataframe must report 100% completeness with no missing-value issues."""
    issues, by_col, overall = compute_completeness(clean_pa_df, sparse_cols=set())
    assert overall == pytest.approx(1.0, abs=1e-9)
    assert all(rate == 1.0 for rate in by_col.values())
    assert not [i for i in issues if i["type"] == "missing_values"]


def test_check_naming_conventions_flags_camelcase() -> None:
    """check_naming_conventions must flag a CamelCase column name."""
    df = pd.DataFrame({"goodCol": [1], "snake_ok": [2]})
    issues = check_naming_conventions(df)
    flagged = {i["column"] for i in issues}
    assert "goodCol" in flagged
    assert "snake_ok" not in flagged


def test_detect_duplicate_rows_counts_exact_dups() -> None:
    """detect_duplicate_rows must report exact-duplicate count when there are dups."""
    df = pd.DataFrame({"a": [1, 1, 2, 3], "b": ["x", "x", "y", "z"]})
    issues = detect_duplicate_rows(df)
    assert any(i["type"] == "duplicate_rows" for i in issues)


def test_detect_rare_categories_flags_under_one_percent() -> None:
    """A value occurring once in 200 rows must be flagged as a rare category."""
    df = pd.DataFrame({"cat": ["A"] * 199 + ["B"]})
    issues = detect_rare_categories(df, ["cat"])
    assert any(i["column"] == "cat" for i in issues)


def test_detect_outliers_uses_iqr_not_sigma() -> None:
    """B5 closure: detect_outliers must use the 3xIQR Tukey fence, not mean +- 3*std.

    A heavy-tailed input where ``mean + 3*std`` would still bracket the high
    tail but ``q3 + 3*iqr`` would not. The IQR fence must call them outliers.
    """
    rng = np.random.default_rng(7)
    bulk = rng.normal(loc=10.0, scale=1.0, size=200)
    spikes = np.array([200.0, 250.0, 300.0])
    values = np.concatenate([bulk, spikes])
    df = pd.DataFrame({"x": values})

    issues = detect_outliers(df, ["x"])
    assert issues, "expected at least one outlier issue on the spiked series"
    detail = issues[0]["detail"]

    q1, q3 = np.quantile(values, 0.25), np.quantile(values, 0.75)
    iqr = q3 - q1
    iqr_upper = q3 + 3 * iqr

    sigma_upper = float(values.mean() + 3 * values.std())
    assert iqr_upper < sigma_upper, "IQR fence must sit below sigma fence on this fixture"
    assert "IQR" in detail or "fence" in detail


def test_normalize_period_column_handles_all_supported_formats() -> None:
    """normalize_period_column canonicalises every supported period format to MM-YYYY."""
    df = pd.DataFrame(
        {
            "rata": ["202401", "2024-02", "mar-2024", "04/2024", "Rata 2024"],
        }
    )
    _n_norm, n_null = normalize_period_column(df, "rata")
    out = df["rata"].tolist()
    assert out[0] == "01-2024"
    assert out[1] == "02-2024"
    assert out[2] == "03-2024"
    assert out[3] == "04-2024"
    assert pd.isna(out[4])
    assert n_null >= 1


def test_apply_lookup_imputation_vectorized_equivalence(
    wide_dirty_df: pd.DataFrame,
) -> None:
    """H5 parity: tools.apply_lookup_imputation must match the legacy row-by-row impl.

    Before Step 6, both are the same loop, so the test trivially holds. After
    Step 6 it confirms the new vectorised implementation produces identical
    cell-level updates and the same return value.
    """
    lookup = {"RM": "Roma", "MI": "Milano", "NA": "Napoli", "TO": "Torino", "BA": "Bari"}

    legacy_df = wide_dirty_df.copy()
    new_df = wide_dirty_df.copy()

    legacy_count = _legacy_apply_lookup_imputation(legacy_df, "region_code", "capoluogo", lookup)
    new_count = apply_lookup_imputation(new_df, "region_code", "capoluogo", lookup)

    assert new_count == legacy_count
    assert legacy_df["capoluogo"].equals(new_df["capoluogo"])


def test_check_format_pattern_includes_pattern_field() -> None:
    """B1 closure: check_format_pattern must echo the regex back in its issue dict."""
    df = pd.DataFrame({"id": ["AB12", "Z9", "ABC123", "AB34"]})
    issues = check_format_pattern(df, "id", r"^[A-Z]{2}\d{2}$", "two letters + two digits")
    assert issues, "expected at least one issue for the violating rows"
    issue = issues[0]
    assert "pattern" in issue
    assert issue["pattern"] == r"^[A-Z]{2}\d{2}$"
    assert issue.get("description") == "two letters + two digits"


def test_currency_symbol_auto_fix() -> None:
    """A3 closure: stripping currency symbols + whitespace must yield a clean numeric column."""
    from tools import fix_currency_symbols_in_numeric

    df = pd.DataFrame({"importo": ["\u20ac 1234.56", "$ 99.99", "100.00", "\u00a3 1.00"]})
    fix_currency_symbols_in_numeric(df, "importo")
    coerced = pd.to_numeric(df["importo"], errors="coerce")
    assert coerced.notna().all()


def test_comma_decimal_auto_fix() -> None:
    """A3 closure: comma-decimals must be canonicalised; canonical values pass through unchanged."""
    from tools import fix_comma_decimal_format

    df = pd.DataFrame({"importo": ["1.234,56", "1234.56", "abc", "999,9"]})
    fix_comma_decimal_format(df, "importo")
    out = df["importo"].tolist()
    assert out[0] == "1234.56"
    assert out[1] == "1234.56"
    assert out[2] == "abc"
    assert out[3] == "999.9"


def test_check_numeric_corruption_types_classifies_three_subtypes() -> None:
    from tools import check_numeric_corruption_types

    df = pd.DataFrame(
        {
            "importo": [
                "€ 100",
                "$ 50",
                "1.234,56",
                "999,9",
                "N.D.",
                "n.c.",
                "42",
                "100.0",
            ]
        }
    )
    issues = check_numeric_corruption_types(df, "importo")
    types = {i["type"] for i in issues}
    assert "currency_symbol_in_numeric" in types
    assert "comma_decimal_format" in types
    assert "nd_placeholder_in_numeric" in types


def test_check_numeric_corruption_types_returns_empty_on_clean_column() -> None:
    from tools import check_numeric_corruption_types

    df = pd.DataFrame({"importo": ["100", "200.5", "300"]})
    assert check_numeric_corruption_types(df, "importo") == []


def test_check_numeric_corruption_types_unknown_column_returns_empty() -> None:
    from tools import check_numeric_corruption_types

    df = pd.DataFrame({"a": [1, 2, 3]})
    assert check_numeric_corruption_types(df, "missing_column") == []


def test_check_month_column_flags_text_names_and_special_codes() -> None:
    from tools import check_month_column

    values: list[Any] = list(range(1, 13)) * 10
    values[0] = "March"
    values[1] = "September"
    values[2] = -1
    values[3] = 13
    values[4] = 99
    df = pd.DataFrame({"month": values})
    issues = check_month_column(df, ["month"])
    types = {i["type"] for i in issues}
    assert "month_format_inconsistency" in types
    assert "special_month_code" in types


def test_check_year_column_flags_dirty_two_digit_and_invalid() -> None:
    from tools import check_year_column

    base = [str(y) for y in range(1990, 2024)]
    dirty = [*base, "2024.", "2024.", "12", "99", "1800", "2200"]
    df = pd.DataFrame({"year": dirty})
    issues = check_year_column(df, ["year"])
    types = {i["type"] for i in issues}
    assert "year_format_inconsistency" in types
    assert "ambiguous_year_format" in types
    assert "invalid_year_value" in types


def test_check_year_column_skips_short_columns() -> None:
    from tools import check_year_column

    df = pd.DataFrame({"year": ["2020", "2021"]})
    assert check_year_column(df, ["year"]) == []


def test_check_period_formats_flags_mixed_formats() -> None:
    from tools import check_period_formats

    values = ["202401", "2024-02", "mar-2024", "04/2024", "Rata 2024", "garbage"]
    values *= 30
    df = pd.DataFrame({"rata": values})
    issues = check_period_formats(df, ["rata"])
    assert any(i["type"] == "period_format_inconsistency" for i in issues)


def test_fix_invalid_dates_yyyymm_period_codes() -> None:
    from tools import fix_invalid_dates

    df = pd.DataFrame({"period": ["202401", "202402", "202403", "202404", "202405", "garbage"]})
    method, count = fix_invalid_dates(df, "period")
    assert method == "YYYYMM_validated"
    assert count == 5


def test_fix_invalid_dates_italian_month_names() -> None:
    from tools import fix_invalid_dates

    values = [
        "11 giu 2024",
        "12 lug 2024",
        "13 ago 2024",
        "14 set 2024",
        "15 ott 2024",
    ]
    df = pd.DataFrame({"d": values})
    method, count = fix_invalid_dates(df, "d")
    assert count >= 3
    assert method != ""


def test_fix_invalid_dates_unknown_column_returns_empty() -> None:
    from tools import fix_invalid_dates

    df = pd.DataFrame({"a": [1, 2, 3]})
    method, count = fix_invalid_dates(df, "missing")
    assert method == ""
    assert count == 0


def test_fix_special_month_codes_nulls_codes_in_place() -> None:
    from tools import fix_special_month_codes

    df = pd.DataFrame({"month": [1, 2, -1, 0, 13, 99, 7, 8]})
    n = fix_special_month_codes(df, "month")
    assert n == 4
    assert df["month"].isna().sum() == 4


def test_fix_special_month_codes_unknown_column_returns_zero() -> None:
    from tools import fix_special_month_codes

    df = pd.DataFrame({"a": [1, 2, 3]})
    assert fix_special_month_codes(df, "missing") == 0


def test_apply_lookup_imputation_no_columns_returns_zero() -> None:
    df = pd.DataFrame({"a": [1, 2], "b": [None, None]})
    assert apply_lookup_imputation(df, "missing", "b", {"x": "y"}) == 0
    assert apply_lookup_imputation(df, "a", "missing", {"1": "y"}) == 0
    assert apply_lookup_imputation(df, "a", "b", {}) == 0


def test_apply_lookup_imputation_no_imputable_rows_returns_zero() -> None:
    df = pd.DataFrame({"src": ["RM", "MI"], "tgt": ["Roma", "Milano"]})
    n = apply_lookup_imputation(df, "src", "tgt", {"RM": "Roma", "MI": "Milano"})
    assert n == 0
