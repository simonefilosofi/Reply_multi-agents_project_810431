"""Shared constants used across multiple agents in the data quality pipeline."""

import re

PLACEHOLDERS = {
    "n/a", "na", "n.a.", "n.d.", "nd", "n/d", "null", "none", "-",
    "--", ".", "..", "...", "unknown", "missing", "tbd",
    "not available", "not applicable", "sconosciuto",
    "non disponibile", "non applicabile",
    "//", "///", "?", "??", "???", "#", "#n/d", "#nd", "#n/a",
    "error",
}

DATE_PATTERNS = [
    ("DD/MM/YYYY", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")),
    ("DD-MM-YYYY", re.compile(r"^\d{2}-\d{2}-\d{4}$")),
    ("DD.MM.YYYY", re.compile(r"^\d{2}\.\d{2}\.\d{4}$")),
    ("YYYY-MM-DD", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("YYYYMMDD", re.compile(r"^\d{8}$")),
]

DATE_FORMAT_MAP = {
    "DD/MM/YYYY": "%d/%m/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYYMMDD": "%Y%m%d",
}

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

# Canonical issue type vocabulary. Every issue dict in the pipeline must use
# one of these keys as its "type" field. Grouped by the agent that owns them.
ISSUE_TYPES = {
    # SchemaAgent
    "mixed_type":                  "column contains both numeric and non-numeric values",
    "invalid_dates":               "date values that cannot be parsed",
    "naming_convention":           "column name violates snake_case convention",
    # CompletenessAgent
    "missing_values":              "null or empty values",
    "placeholder_values":          "sentinel strings (N/A, N.D., unknown…) used instead of NULL",
    "sparse_column":               "column is mostly empty (>90% missing)",
    # DuplicateAgent
    "duplicate_rows":              "exact duplicate rows",
    "duplicate_columns":           "two columns with identical or near-identical values",
    "duplicate_key":               "rows sharing a key value but differing elsewhere",
    # AnomalyAgent
    "outliers":                    "statistical outliers (3-sigma rule)",
    "rare_categories":             "categorical values appearing in <1% of rows",
    # ConsistencyAgent
    "format_inconsistency":        "mixed date or string formats within one column",
    "case_inconsistency":          "same values in different cases (e.g. RM vs rm)",
    "date_order":                  "end date earlier than start date in the same row",
    "conditional_completeness":    "column B missing when column A has a value",
    "lookup_imputability":         "missing values can be inferred from a related column via a learned mapping",
    # ConstraintAgent
    "float_precision_noise":       "floating-point noise (1.000000001 instead of 1.0)",
    "format_pattern_violation":    "values not matching the expected regex pattern",
    "cross_column_mismatch":       "two columns that should agree but don't",
    "domain_negative_values":      "negative values in a non-negative column",
    "currency_symbol_in_numeric":  "currency symbols present in a numeric column",
    "comma_decimal_format":        "comma used as decimal separator instead of dot",
    "nd_placeholder_in_numeric":   "N.D. / N.A. placeholders in a numeric column",
    "fractional_integers":         "non-trivial fractional parts in an integer column",
    "period_format_inconsistency": "period (YYYYMM) values stored in mixed formats",
    "month_format_inconsistency":  "month values as text names or out-of-range integers",
    "special_month_code":          "special codes (0, 13, 99…) used as month values",
    "year_format_inconsistency":   "year values with trailing noise or non-digit chars",
    "ambiguous_year_format":       "2-digit year values requiring century expansion",
    "invalid_year_value":          "year values outside the plausible range [1900-2099]",
}

# Per-agent subsets — only these types are valid for each agent's LLM enrichment.
SCHEMA_ISSUE_TYPES      = {"mixed_type", "invalid_dates", "naming_convention"}
COMPLETENESS_ISSUE_TYPES = {"missing_values", "placeholder_values", "sparse_column"}
DUPLICATE_ISSUE_TYPES   = {"duplicate_rows", "duplicate_columns", "duplicate_key"}
ANOMALY_ISSUE_TYPES     = {"outliers", "rare_categories"}
CONSISTENCY_ISSUE_TYPES = {"format_inconsistency", "case_inconsistency",
                            "date_order", "conditional_completeness",
                            "lookup_imputability"}
CONSTRAINT_ISSUE_TYPES  = {
    "float_precision_noise", "format_pattern_violation", "cross_column_mismatch",
    "domain_negative_values", "currency_symbol_in_numeric", "comma_decimal_format",
    "nd_placeholder_in_numeric", "fractional_integers", "period_format_inconsistency",
    "month_format_inconsistency", "special_month_code", "year_format_inconsistency",
    "ambiguous_year_format", "invalid_year_value",
}

# Types the LLM may use in post-remediation gap detection.
# Excludes types that are always fully handled by deterministic fixers
# (missing_values, duplicate_rows, naming_convention, etc.) so the LLM
# only reports issues that could genuinely remain after the deterministic pass.
GAP_DETECTION_ISSUE_TYPES = {
    "mixed_type", "invalid_dates", "placeholder_values",
    "format_inconsistency", "case_inconsistency",
    "float_precision_noise", "format_pattern_violation",
    "cross_column_mismatch", "domain_negative_values",
    "currency_symbol_in_numeric", "comma_decimal_format",
    "nd_placeholder_in_numeric", "fractional_integers",
    "period_format_inconsistency", "month_format_inconsistency",
    "special_month_code", "year_format_inconsistency",
    "ambiguous_year_format", "invalid_year_value",
}
