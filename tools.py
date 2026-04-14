"""Pure Python tool functions used by pipeline agents.

All functions here are stateless: they receive data in and return results out.
No LLM calls, no PipelineState access, no logging.
"""

import csv
import json
import re
from itertools import combinations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from state_demo.constants import DATE_FORMAT_MAP, DATE_PATTERNS, PLACEHOLDERS
from state_demo.fingerprint_schema import DatasetFingerprint
from state_demo.helpers import missing_mask, non_empty_values

# ── Schema: reserved words ─────────────────────────────────────────────────────
RESERVED_WORDS = {
    "class", "def", "return", "import", "from", "lambda", "global",
    "none", "true", "false", "and", "or", "not", "in", "is",
    "if", "else", "for", "while", "try", "except", "with", "as",
    "pass", "break", "continue", "yield",
    "select", "where", "join", "insert", "update", "delete", "drop",
    "table", "index", "group", "order", "having", "union", "create",
    "alter",
    "values", "columns", "dtypes", "shape", "name", "count",
}


# ── Ingestion ──────────────────────────────────────────────────────────────────

def load_dataset(path: str) -> tuple[pd.DataFrame, str]:
    """Load a dataset from CSV, JSON, Excel, or Parquet.

    Returns (df, extension) where df is fully string-typed.
    """
    ext = path.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            sample = f.read(8192)
        try:
            dialect = csv.Sniffer().sniff(sample)
            sep = dialect.delimiter
        except csv.Error:
            sep = ","
        df = pd.read_csv(
            path, sep=sep, dtype=str,
            encoding="utf-8", on_bad_lines="warn",
        )
    elif ext == "json":
        with open(path, encoding="utf-8") as f:
            df = pd.json_normalize(json.load(f)).astype(str)
    elif ext in ("xlsx", "xls"):
        df = pd.read_excel(path, dtype=str)
    elif ext == "parquet":
        df = pd.read_parquet(path).astype(str)
    else:
        raise ValueError(f"Unsupported format: {ext}")
    return df, ext


# ── Profiling ──────────────────────────────────────────────────────────────────

def compute_column_stats(df: pd.DataFrame) -> str:
    """Build a column-statistics block string for the profiler LLM prompt."""
    lines = []
    for col in df.columns:
        nev = non_empty_values(df[col])
        lines.append(
            f"- {col!r}: {len(nev)}/{len(df)} non-empty, "
            f"{nev.nunique()} unique, "
            f"sample={list(nev.head(5))}"
        )
    return "\n".join(lines)


def statistical_fingerprint(df: pd.DataFrame) -> dict:
    """Fallback fingerprint built from statistical heuristics (no LLM)."""
    numerical, categorical, date_cols, id_cols, sparse = [], [], [], [], []

    for col in df.columns:
        nev = non_empty_values(df[col])
        if len(df) == 0:
            continue

        null_rate = 1 - len(nev) / len(df)
        if null_rate > 0.90:
            sparse.append(col)
            continue

        num_frac = pd.to_numeric(nev, errors="coerce").notna().mean()
        if num_frac > 0.80:
            numerical.append(col)
        else:
            date_detected = False
            sample = nev.astype(str).head(100)
            pure_int_frac = sample.str.match(r"^\d+$").mean()
            if pure_int_frac <= 0.80:
                parsed_df = pd.to_datetime(sample, errors="coerce", dayfirst=True)
                parsed_nd = pd.to_datetime(sample, errors="coerce")
                date_rate = max(parsed_df.notna().mean(), parsed_nd.notna().mean())
                if date_rate > 0.50:
                    date_cols.append(col)
                    date_detected = True
            if not date_detected and nev.nunique() / max(len(nev), 1) < 0.05:
                categorical.append(col)

        col_lower = col.lower().strip()
        col_tokens = set(col_lower.split("_"))
        id_indicators = {"codice", "matricola", "fiscal", "cf"}
        if (
            col_lower in ("_id", "id")
            or col_lower.endswith("_id")
            or bool(col_tokens & id_indicators)
        ):
            if col not in id_cols:
                id_cols.append(col)

    return {
        "domain": "generic",
        "language": "mixed",
        "id_columns": id_cols,
        "numerical_columns": numerical,
        "categorical_columns": categorical,
        "date_columns": date_cols,
        "sparse_columns": sparse,
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
    }


# ── Schema ─────────────────────────────────────────────────────────────────────

def check_type_issues(
    df: pd.DataFrame,
    numerical_cols: list,
    date_cols: list,
) -> list:
    """Check for type mismatches in numerical and date columns."""
    issues = []

    for col in numerical_cols:
        if col not in df.columns:
            continue
        nev = non_empty_values(df[col])
        if len(nev) == 0:
            continue
        non_numeric = int(pd.to_numeric(nev, errors="coerce").isna().sum())
        if non_numeric > 0:
            pct = non_numeric / len(nev)
            severity = "high" if pct > 0.20 else ("medium" if pct > 0.05 else "low")
            issues.append({
                "column": col,
                "type": "mixed_type",
                "detail": (
                    f"Expected numeric but {non_numeric} values "
                    f"({pct:.0%}) cannot parse as numbers"
                ),
                "severity": severity,
            })

    for col in date_cols:
        if col not in df.columns:
            continue
        nev = non_empty_values(df[col])
        bad_frac = pd.to_datetime(nev, errors="coerce", dayfirst=True).isna().mean()
        if bad_frac > 0.10:
            issues.append({
                "column": col,
                "type": "invalid_dates",
                "detail": f"{bad_frac:.0%} values cannot be parsed as dates",
                "severity": "medium",
            })

    return issues


def check_naming_conventions(df: pd.DataFrame) -> list:
    """Check column names against snake_case and reserved word rules."""
    issues = []
    for col in df.columns:
        violations = []
        if col != col.strip():
            violations.append("leading/trailing whitespace")
        if " " in col.strip():
            violations.append("contains spaces")
        if re.search(r"[^a-zA-Z0-9_ ]", col):
            violations.append("contains special characters")
        if col != col.lower():
            violations.append("not snake_case (contains uppercase)")
        if col.strip().lower() in RESERVED_WORDS:
            violations.append(f"'{col.strip().lower()}' is a reserved word")
        if violations:
            issues.append({
                "column": col,
                "type": "naming_convention",
                "detail": "; ".join(violations),
                "severity": "low",
            })
    return issues


# ── Completeness ───────────────────────────────────────────────────────────────

def compute_completeness(
    df: pd.DataFrame,
    sparse_cols: set,
) -> tuple[list, dict, float]:
    """Compute per-column completeness and detect missing/placeholder issues.

    Returns (issues, completeness_by_column, overall_completeness).
    """
    issues = []
    completeness_by_column = {}
    total_missing_all = 0

    for col in df.columns:
        total = len(df)
        missing_count = int(missing_mask(df[col]).sum())
        rate = missing_count / total if total > 0 else 0
        completeness_by_column[col] = 1 - rate
        total_missing_all += missing_count

        if rate > 0.50:
            severity = "high"
        elif rate > 0.20:
            severity = "medium"
        elif rate > 0.05:
            severity = "low"
        else:
            continue

        issues.append({
            "column": col,
            "type": "missing_values",
            "detail": (
                f"{rate:.0%} of values are missing, empty, or placeholder "
                f"({missing_count}/{total})"
            ),
            "severity": severity,
        })

    for col in sparse_cols:
        if col not in df.columns:
            continue
        empty_pct = 1 - completeness_by_column.get(col, 1.0)
        issues.append({
            "column": col,
            "type": "sparse_column",
            "detail": f"Column is {empty_pct:.0%} empty \u2014 candidate for removal",
            "severity": "medium",
        })

    total_cells = len(df) * len(df.columns)
    overall = 1 - (total_missing_all / total_cells) if total_cells > 0 else 1.0
    return issues, completeness_by_column, overall


# ── Consistency ────────────────────────────────────────────────────────────────

def check_date_format_consistency(df: pd.DataFrame, date_cols: list) -> list:
    """Detect columns where multiple date formats are in use."""
    issues = []
    for col in date_cols:
        if col not in df.columns:
            continue
        nev = non_empty_values(df[col])
        if len(nev) < 10:
            continue
        values = nev.astype(str).str.strip()
        pattern_counts: dict[str, int] = {}
        for val in values:
            for label, regex in DATE_PATTERNS:
                if regex.match(val):
                    pattern_counts[label] = pattern_counts.get(label, 0) + 1
                    break
        total_matched = sum(pattern_counts.values())
        if total_matched == 0:
            continue
        significant = [
            label for label, cnt in pattern_counts.items()
            if cnt / total_matched > 0.05
        ]
        if len(significant) >= 2:
            detail = ", ".join(
                f"{label} ({pattern_counts[label]})" for label in significant
            )
            issues.append({
                "column": col,
                "type": "format_inconsistency",
                "detail": f"{len(significant)} date formats detected: {detail}",
                "severity": "medium",
            })
    return issues


def check_date_ordering(df: pd.DataFrame, date_cols: list) -> list:
    """Detect pairs of date columns where chronological order is violated."""
    issues = []
    for col_a, col_b in combinations(date_cols, 2):
        if col_a not in df.columns or col_b not in df.columns:
            continue
        parsed_a = pd.to_datetime(df[col_a], errors="coerce", dayfirst=True)
        parsed_b = pd.to_datetime(df[col_b], errors="coerce", dayfirst=True)
        both_valid = parsed_a.notna() & parsed_b.notna()
        if both_valid.sum() < 10:
            continue
        violations = int((parsed_a[both_valid] > parsed_b[both_valid]).sum())
        if violations > 0:
            issues.append({
                "column": f"{col_a} / {col_b}",
                "type": "date_order",
                "detail": (
                    f"{violations} rows where '{col_a}' is later than '{col_b}'"
                ),
                "severity": (
                    "high" if violations / both_valid.sum() > 0.05 else "medium"
                ),
            })
    return issues


def check_case_consistency(df: pd.DataFrame, cat_cols: list) -> list:
    """Detect categorical columns with mixed-case variants of the same value."""
    issues = []
    for col in cat_cols:
        if col not in df.columns:
            continue
        nev = non_empty_values(df[col])
        if len(nev) < 10:
            continue
        stripped = nev.astype(str).str.strip()
        raw_unique = stripped.nunique()
        lower_unique = stripped.str.lower().nunique()
        if raw_unique <= lower_unique:
            continue
        difference = raw_unique - lower_unique
        if difference > 3 and difference / raw_unique > 0.05:
            issues.append({
                "column": col,
                "type": "case_inconsistency",
                "detail": (
                    f"{difference} values differ only by case "
                    f"({raw_unique} unique raw vs {lower_unique} unique lowercase)"
                ),
                "severity": "low",
            })
    return issues


def check_conditional_completeness(df: pd.DataFrame, fp: dict) -> list:
    """Detect pairs of related columns where one is filled but the other is empty."""
    issues = []
    id_cols_set = set(fp.get("id_columns", []))
    col_list = list(df.columns)

    related_pairs = [
        (col_a, col_b)
        for col_a, col_b in combinations(col_list, 2)
        if col_a.split("_")[0].lower() == col_b.split("_")[0].lower()
        and len(col_a.split("_")[0]) >= 4
        and col_a not in id_cols_set
        and col_b not in id_cols_set
    ]

    for col_a, col_b in related_pairs:
        filled_a = df[col_a].notna() & (df[col_a].astype(str).str.strip() != "")
        filled_b = df[col_b].notna() & (df[col_b].astype(str).str.strip() != "")
        if filled_a.sum() < 10:
            continue
        fill_rate = filled_b[filled_a].mean()
        if 0.90 <= fill_rate < 1.0:
            missing_when_a = int((filled_a & ~filled_b).sum())
            issues.append({
                "column": f"{col_a} / {col_b}",
                "type": "conditional_completeness",
                "detail": (
                    f"{missing_when_a} rows have '{col_a}' filled "
                    f"but '{col_b}' empty"
                ),
                "severity": "low",
            })

    return issues


# ── Duplicates ─────────────────────────────────────────────────────────────────

def detect_duplicate_rows(df: pd.DataFrame) -> list:
    """Detect fully duplicate rows."""
    issues = []
    dup_rows = int(df.duplicated().sum())
    if dup_rows > 0:
        issues.append({
            "column": "_rows_",
            "type": "duplicate_rows",
            "detail": (
                f"{dup_rows} fully duplicate rows "
                f"({dup_rows / len(df):.1%} of dataset)"
            ),
            "severity": "high" if dup_rows / len(df) > 0.05 else "medium",
        })
    return issues


def detect_duplicate_columns(df: pd.DataFrame, likely_pairs: list) -> list:
    """Flag column pairs identified by the profiler as likely containing the same data."""
    issues = []
    for pair in likely_pairs:
        if len(pair) == 2 and pair[0] in df.columns and pair[1] in df.columns:
            issues.append({
                "column": f"{pair[0]} / {pair[1]}",
                "type": "duplicate_columns",
                "detail": (
                    f"Columns '{pair[0]}' and '{pair[1]}' appear to contain "
                    f"the same data"
                ),
                "severity": "medium",
            })
    return issues


def detect_key_collisions(
    df: pd.DataFrame, key_cols: list
) -> tuple[list, str]:
    """Detect rows sharing key column values but differing in other columns.

    Returns (issues, skip_reason). skip_reason is non-empty when no check was done.
    """
    if not key_cols:
        return [], "No valid key columns identified -- skipping key-collision check"
    collisions = df.duplicated(subset=key_cols, keep=False)
    full_dups = df.duplicated(keep=False)
    key_only = collisions & ~full_dups
    n_key_only = int(key_only.sum())
    issues = []
    if n_key_only > 0:
        col_list = ", ".join(key_cols)
        issues.append({
            "column": col_list,
            "type": "duplicate_key",
            "detail": (
                f"{n_key_only} rows share the same key values in [{col_list}] "
                f"but differ in other columns "
                f"-- possible duplicate records or data entry errors"
            ),
            "severity": "high",
        })
    return issues, ""


# ── Anomalies ──────────────────────────────────────────────────────────────────

def detect_outliers(df: pd.DataFrame, numerical_cols: list) -> list:
    """Detect values beyond 3 standard deviations in numerical columns."""
    issues = []
    for col in numerical_cols:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(numeric) < 10:
            continue
        mean, std = numeric.mean(), numeric.std()
        if std == 0:
            continue
        outliers = int(((numeric - mean).abs() > 3 * std).sum())
        if outliers > 0:
            issues.append({
                "column": col,
                "type": "outliers",
                "detail": f"{outliers} values beyond 3 standard deviations",
                "severity": "medium",
            })
    return issues


def detect_rare_categories(df: pd.DataFrame, categorical_cols: list) -> list:
    """Detect categories appearing in less than 1% of rows."""
    issues = []
    for col in categorical_cols:
        if col not in df.columns:
            continue
        counts = df[col].value_counts(normalize=True)
        rare = counts[counts < 0.01]
        if len(rare) > 0:
            issues.append({
                "column": col,
                "type": "rare_categories",
                "detail": f"{len(rare)} categories appear in less than 1% of rows",
                "severity": "low",
            })
    return issues


# ── Constraints ───────────────────────────────────────────────────────────────

def check_column_value_agreement(
    df: pd.DataFrame, col_a: str, col_b: str
) -> list:
    """Flag rows where two columns that should be equal actually disagree."""
    if col_a not in df.columns or col_b not in df.columns:
        return []
    a = df[col_a].astype(str).str.strip()
    b = df[col_b].astype(str).str.strip()
    both_filled = (
        df[col_a].notna() & (a != "") & (a.str.lower() != "nan")
        & df[col_b].notna() & (b != "") & (b.str.lower() != "nan")
    )
    if both_filled.sum() < 5:
        return []
    mismatches = int((a[both_filled] != b[both_filled]).sum())
    if mismatches == 0:
        return []
    pct = mismatches / both_filled.sum()
    severity = "high" if pct > 0.05 else "medium"
    return [{
        "column": f"{col_a} / {col_b}",
        "type": "cross_column_mismatch",
        "detail": (
            f"{mismatches} rows ({pct:.0%}) where '{col_a}' and '{col_b}' "
            f"should agree but differ"
        ),
        "severity": severity,
    }]


def check_domain_negatives(df: pd.DataFrame, col: str) -> list:
    """Flag negative values in a column where negatives are domain-impossible."""
    if col not in df.columns:
        return []
    numeric = pd.to_numeric(df[col], errors="coerce")
    neg_count = int((numeric < 0).sum())
    if neg_count == 0:
        return []
    return [{
        "column": col,
        "type": "domain_negative_values",
        "detail": (
            f"{neg_count} negative values in a column where negatives "
            f"are domain-impossible"
        ),
        "severity": "high",
    }]


def check_format_pattern(
    df: pd.DataFrame, col: str, pattern: str, description: str
) -> list:
    """Flag values that do not match the expected regex pattern."""
    if col not in df.columns:
        return []
    nev = non_empty_values(df[col])
    if len(nev) == 0:
        return []
    try:
        compiled = re.compile(pattern)
    except re.error:
        return []
    violations = nev.astype(str).apply(lambda v: not compiled.match(v))
    n_violations = int(violations.sum())
    if n_violations == 0:
        return []
    pct = n_violations / len(nev)
    severity = "high" if pct > 0.20 else ("medium" if pct > 0.05 else "low")
    return [{
        "column": col,
        "type": "format_pattern_violation",
        "detail": (
            f"{n_violations} values ({pct:.0%}) do not match expected "
            f"format: {description}"
        ),
        "severity": severity,
    }]


def check_numeric_corruption_types(df: pd.DataFrame, col: str) -> list:
    """Classify WHY a numeric column has non-numeric values (symbols, comma
    decimals, ND placeholders)."""
    if col not in df.columns:
        return []
    nev = non_empty_values(df[col])
    non_numeric_mask = pd.to_numeric(nev, errors="coerce").isna()
    bad = nev[non_numeric_mask].astype(str)
    if len(bad) == 0:
        return []

    issues = []

    currency_count = int(bad.str.contains(r"[€$£¥]", regex=True).sum())
    if currency_count > 0:
        issues.append({
            "column": col,
            "type": "currency_symbol_in_numeric",
            "detail": (
                f"{currency_count} values contain currency symbols "
                f"(e.g. €) that prevent numeric parsing"
            ),
            "severity": "high",
        })

    comma_decimal_count = int(
        bad.str.match(r"^\d{1,3}(\.\d{3})*(,\d+)?$").sum()
    )
    if comma_decimal_count > 0:
        issues.append({
            "column": col,
            "type": "comma_decimal_format",
            "detail": (
                f"{comma_decimal_count} values use comma as decimal "
                f"separator (Italian locale format)"
            ),
            "severity": "high",
        })

    nd_patterns = {"n.d.", "nd", "n/d", "n.a.", "na", "n/a", "#n/d", "#nd"}
    nd_count = int(bad.str.lower().str.strip().isin(nd_patterns).sum())
    if nd_count > 0:
        issues.append({
            "column": col,
            "type": "nd_placeholder_in_numeric",
            "detail": (
                f"{nd_count} values use 'N.D.' or similar placeholder "
                f"instead of a proper NULL"
            ),
            "severity": "medium",
        })

    return issues


def check_float_precision(
    df: pd.DataFrame, numerical_cols: list, max_decimals: int = 2
) -> list:
    """Flag numeric columns with excessive decimal digits (floating-point noise)."""
    issues = []
    for col in numerical_cols:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(numeric) == 0:
            continue
        noisy = numeric.apply(
            lambda v: len(str(v).split(".")[-1]) > max_decimals
            if "." in str(v) else False
        )
        n_noisy = int(noisy.sum())
        if n_noisy > len(numeric) * 0.10:
            issues.append({
                "column": col,
                "type": "float_precision_noise",
                "detail": (
                    f"{n_noisy} values have more than {max_decimals} "
                    f"decimal places — likely floating-point arithmetic noise"
                ),
                "severity": "low",
            })
    return issues


# ── Remediation ────────────────────────────────────────────────────────────────

def fix_mixed_type(df: pd.DataFrame, col: str) -> int:
    """Coerce column to numeric in-place. Returns number of values that became NaN."""
    if col not in df.columns:
        return 0
    before_na = int(df[col].isna().sum())
    df[col] = pd.to_numeric(df[col], errors="coerce")
    return int(df[col].isna().sum()) - before_na


def fix_invalid_dates(df: pd.DataFrame, col: str) -> tuple[str, int]:
    """Re-parse a date column choosing the best dayfirst setting in-place.

    Returns (method_used, valid_count).
    """
    if col not in df.columns:
        return "", 0
    parsed_df = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    parsed_nd = pd.to_datetime(df[col], errors="coerce", dayfirst=False)
    if parsed_df.notna().sum() >= parsed_nd.notna().sum():
        df[col] = parsed_df
        return "dayfirst=True", int(parsed_df.notna().sum())
    else:
        df[col] = parsed_nd
        return "dayfirst=False", int(parsed_nd.notna().sum())


def remove_duplicate_rows(df: pd.DataFrame) -> int:
    """Drop fully duplicate rows in-place. Returns number removed."""
    before = len(df)
    df.drop_duplicates(inplace=True)
    df.reset_index(drop=True, inplace=True)
    return before - len(df)


def fill_missing_numerical(
    df: pd.DataFrame, col: str, is_missing: pd.Series
) -> tuple[bool, str]:
    """Fill missing values in a numerical column with the column median in-place.

    Returns (success, detail_message).
    """
    if col not in df.columns:
        return False, "Column not found"
    numeric = pd.to_numeric(df[col], errors="coerce")
    median_val = numeric.median()
    if pd.notna(median_val):
        df[col] = numeric.fillna(median_val)
        return True, f"Filled {int(is_missing.sum())} missing values with median ({median_val:.2f})"
    return False, "Cannot compute median -- all values non-numeric"


def fill_missing_categorical(
    df: pd.DataFrame,
    col: str,
    is_missing: pd.Series,
    severity: str,
) -> tuple[bool, str]:
    """Fill missing values in a categorical column with the mode in-place.

    High-severity columns (>50% missing) are flagged rather than filled.
    Returns (success, detail_message).
    """
    if col not in df.columns:
        return False, "Column not found"
    rows_affected = int(is_missing.sum())
    if severity == "high":
        return False, (
            f"Categorical column with {rows_affected} missing values (>50%) "
            f"-- recommended for removal or domain review"
        )
    clean = df[col][
        ~df[col].astype(str).str.strip().str.lower().isin(PLACEHOLDERS)
        & df[col].notna()
        & (df[col].astype(str).str.strip() != "")
    ]
    if len(clean) > 0:
        mode_value = clean.mode().iloc[0]
        df.loc[is_missing, col] = mode_value
        return True, (
            f"Filled {rows_affected} missing/placeholder values "
            f"with mode ('{mode_value}')"
        )
    return False, "Column is entirely placeholders/empty -- cannot compute safe mode value"


def cap_outliers(
    df: pd.DataFrame, col: str, raw_series: pd.Series
) -> tuple[float, float, int]:
    """Clip outliers in col to the 3-sigma range derived from raw_series in-place.

    Returns (lower, upper, count_capped). Returns (0, 0, 0) if not applicable.
    """
    if col not in df.columns:
        return 0.0, 0.0, 0
    raw_valid = pd.to_numeric(raw_series, errors="coerce").dropna()
    if len(raw_valid) < 2:
        return 0.0, 0.0, 0
    mean, std = raw_valid.mean(), raw_valid.std()
    if std == 0:
        return 0.0, 0.0, 0
    lower, upper = mean - 3 * std, mean + 3 * std
    numeric = pd.to_numeric(df[col], errors="coerce")
    count = int(((numeric - mean).abs() > 3 * std).sum())
    if count > 0:
        df[col] = numeric.clip(lower=lower, upper=upper)
    return lower, upper, count


def standardize_date_format(df: pd.DataFrame, col: str) -> tuple[str, str]:
    """Standardize a date column to the dominant format in-place.

    Returns (action, detail) where action is 'auto_fixed' or 'flagged_for_review'.
    """
    if col not in df.columns:
        return "flagged_for_review", "Column not found"
    if pd.api.types.is_datetime64_any_dtype(df[col]):
        return "auto_fixed", (
            f"Column already parsed as datetime -- format is standardized"
        )
    values = df[col].dropna().astype(str).str.strip()
    pattern_counts: dict[str, int] = {}
    for val in values:
        for label, regex in DATE_PATTERNS:
            if regex.match(val):
                pattern_counts[label] = pattern_counts.get(label, 0) + 1
                break
    if not pattern_counts:
        return "flagged_for_review", "No recognized date patterns found"
    dominant = max(pattern_counts, key=pattern_counts.get)
    fmt = DATE_FORMAT_MAP.get(dominant, "%d/%m/%Y")
    parsed = pd.to_datetime(df[col], errors="coerce", dayfirst=True)
    reformatted = parsed.dt.strftime(fmt)
    reformatted[parsed.isna()] = pd.NA
    changed = int((reformatted != df[col].astype(str)).sum())
    df[col] = reformatted
    return "auto_fixed", f"Standardized {changed} date values to {dominant} format"


def normalize_case(df: pd.DataFrame, col: str) -> int:
    """Normalize string values to the most frequent casing variant in-place.

    Returns number of values changed.
    """
    if col not in df.columns:
        return 0
    original = df[col].copy()
    non_empty_mask = df[col].notna() & (df[col].astype(str).str.strip() != "")
    stripped = df[col].astype(str).str.strip()
    value_counts = stripped[non_empty_mask].value_counts()
    lower_to_best: dict[str, str] = {}
    for val in value_counts.index:
        key = val.lower()
        if key not in lower_to_best:
            lower_to_best[key] = val
    normalized = stripped.str.lower().map(lower_to_best)
    df.loc[non_empty_mask, col] = normalized[non_empty_mask]
    return int((df[col] != original).sum())


def fix_column_naming(df: pd.DataFrame, col: str) -> tuple[str, str]:
    """Rename col to snake_case in-place.

    Returns (old_name, new_name). If old_name == new_name, no rename was done.
    """
    if col not in df.columns:
        return col, col
    new_name = re.sub(r"[^a-z0-9]+", "_", col.lower().strip()).strip("_")
    if not new_name:
        new_name = f"col_{list(df.columns).index(col)}"
    if new_name != col and new_name in df.columns:
        suffix = 2
        while f"{new_name}_{suffix}" in df.columns:
            suffix += 1
        new_name = f"{new_name}_{suffix}"
    if new_name != col:
        df.rename(columns={col: new_name}, inplace=True)
    return col, new_name


# ── Visualizations ─────────────────────────────────────────────────────────────

def chart_severity_distribution(issues: list, images_dir: str) -> str:
    """Bar chart of issue counts by severity. Returns the saved file path."""
    severities = ["high", "medium", "low"]
    counts = [sum(1 for i in issues if i["severity"] == s) for s in severities]
    colors = ["#d9534f", "#f0ad4e", "#5bc0de"]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar([s.capitalize() for s in severities], counts, color=colors)
    for bar, count in zip(bars, counts):
        if count > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height(),
                str(count), ha="center", va="bottom", fontweight="bold",
            )
    ax.set_ylabel("Issue Count")
    ax.set_title("Issue Severity Distribution")

    path = f"{images_dir}/issue_severity_distribution.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def chart_issues_by_agent(issues: list, images_dir: str) -> str:
    """Grouped bar chart of issues per agent broken down by severity. Returns path."""
    agents = ["schema", "completeness", "duplicate", "anomaly", "consistency", "constraint"]
    severities = ["high", "medium", "low"]
    colors = ["#d9534f", "#f0ad4e", "#5bc0de"]

    data = {
        sev: [
            sum(
                1 for i in issues
                if i.get("source") == agent and i["severity"] == sev
            )
            for agent in agents
        ]
        for sev in severities
    }

    x = np.arange(len(agents))
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))
    for idx, sev in enumerate(severities):
        ax.bar(x + idx * width, data[sev], width,
               label=sev.capitalize(), color=colors[idx])
    ax.set_xticks(x + width)
    ax.set_xticklabels([a.capitalize() + "Agent" for a in agents], rotation=15)
    ax.set_ylabel("Issue Count")
    ax.set_title("Issues by Agent and Severity")
    ax.legend()

    path = f"{images_dir}/issues_by_agent.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def chart_completeness_heatmap(
    completeness_by_col: dict, images_dir: str
) -> str:
    """Heatmap of per-column completeness rates. Returns path."""
    if not completeness_by_col:
        return ""
    cols = list(completeness_by_col.keys())
    values = [completeness_by_col[c] for c in cols]
    display_names = [c[:18] + "..." if len(c) > 20 else c for c in cols]

    fig, ax = plt.subplots(figsize=(max(8, len(cols) * 0.6), 2.5))
    data = np.array([values])
    im = ax.imshow(data, cmap="RdYlGn", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(display_names, rotation=45, ha="right", fontsize=8)
    ax.set_yticks([])
    plt.colorbar(im, ax=ax, label="Completeness Rate", shrink=0.8)
    ax.set_title("Completeness Rate by Column (Before Remediation)")
    for idx, val in enumerate(values):
        color = "white" if val < 0.5 else "black"
        ax.text(idx, 0, f"{val:.0%}", ha="center", va="center",
                fontsize=7, color=color)

    path = f"{images_dir}/completeness_heatmap.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


def chart_reliability_comparison(
    before_dims: dict,
    after_dims: dict,
    before_score: float,
    after_score: float,
    images_dir: str,
) -> str:
    """Before-vs-after bar chart of reliability dimension scores. Returns path."""
    all_dim_keys = [
        "schema_conformity", "completeness", "uniqueness",
        "consistency", "anomaly_freedom",
    ]
    labels = [
        "Schema\nConformity", "Completeness", "Uniqueness",
        "Consistency", "Anomaly\nFreedom",
    ]
    present_keys = [
        k for k in all_dim_keys if k in before_dims or k in after_dims
    ]
    present_labels = [labels[all_dim_keys.index(k)] for k in present_keys]
    before_vals = [before_dims.get(k, 0) for k in present_keys]
    after_vals = [after_dims.get(k, 0) for k in present_keys]

    x = np.arange(len(present_keys))
    width = 0.35
    fig, ax = plt.subplots(figsize=(10, 5))
    bars_b = ax.bar(x - width / 2, before_vals, width,
                    label="Before Remediation", color="#6c757d")
    bars_a = ax.bar(x + width / 2, after_vals, width,
                    label="After Remediation", color="#28a745")
    for bar in list(bars_b) + list(bars_a):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, h,
                f"{h:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels(present_labels)
    ax.set_ylabel("Score (0-1)")
    ax.set_ylim(0, 1.15)
    ax.set_title(
        f"Reliability Dimensions: {before_score}/100 -> {after_score}/100"
    )
    ax.legend()

    path = f"{images_dir}/reliability_before_after.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path
