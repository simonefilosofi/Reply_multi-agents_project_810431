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


def _has_column(df: pd.DataFrame, col: str) -> bool:
    """Return True when *col* exists in the dataframe."""
    return col in df.columns


def _coerce_numeric(series: pd.Series, dropna: bool = False) -> pd.Series:
    """Convert a series to numeric using coercion, optionally dropping NaNs."""
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.dropna() if dropna else numeric


def _severity_from_rate(rate: float, high: float = 0.20, medium: float = 0.05) -> str:
    """Map an error rate to a severity label using strict threshold comparisons."""
    if rate > high:
        return "high"
    if rate > medium:
        return "medium"
    return "low"


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


def _looks_like_yyyymm(int_series: pd.Series) -> bool:
    """Return True if the majority of integer values look like YYYYMM period codes."""
    years = int_series // 100
    months = int_series % 100
    valid = (
        (int_series >= 190001) & (int_series <= 209912)
        & (months >= 1) & (months <= 12)
    )
    return valid.mean() > 0.90


def _looks_like_yyyymmdd(int_series: pd.Series) -> bool:
    """Return True if the majority of integer values look like YYYYMMDD date codes."""
    return ((int_series >= 19000101) & (int_series <= 20991231)).mean() > 0.90


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

        num_frac = _coerce_numeric(nev).notna().mean()
        if num_frac > 0.80:
            numeric_vals = _coerce_numeric(nev, dropna=True)
            all_whole = bool((numeric_vals % 1 == 0).all())

            if all_whole and len(numeric_vals) > 0:
                int_vals = numeric_vals.astype(np.int64)

                # YYYYMM period codes → categorical (NOT date_cols: pd.to_datetime
                # cannot parse YYYYMM strings without an explicit format, and
                # fix_invalid_dates would null every value)
                if _looks_like_yyyymm(int_vals):
                    categorical.append(col)
                    continue

                # YYYYMMDD date codes → date column (pd.to_datetime handles these)
                if _looks_like_yyyymmdd(int_vals):
                    date_cols.append(col)
                    continue

                # Low-cardinality integer → categorical (codes, IDs, enumerations)
                if int_vals.nunique() / max(len(int_vals), 1) < 0.10:
                    categorical.append(col)
                    continue

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
        if not _has_column(df, col):
            continue
        nev = non_empty_values(df[col])
        if len(nev) == 0:
            continue
        non_numeric = int(_coerce_numeric(nev).isna().sum())
        if non_numeric > 0:
            pct = non_numeric / len(nev)
            severity = _severity_from_rate(pct)
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
        if not _has_column(df, col):
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
        if col and col[0].isdigit():
            violations.append("starts with a digit (invalid identifier)")
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
    """Flag column pairs containing identical data.

    Checks profiler-suggested pairs first, then runs a deterministic
    value-equality scan across all column combinations.
    """
    issues = []
    already_flagged: set = set()

    for pair in likely_pairs:
        if len(pair) == 2 and pair[0] in df.columns and pair[1] in df.columns:
            key = tuple(sorted(pair))
            already_flagged.add(key)
            issues.append({
                "column": f"{pair[0]} / {pair[1]}",
                "type": "duplicate_columns",
                "detail": (
                    f"Columns '{pair[0]}' and '{pair[1]}' appear to contain "
                    f"the same data"
                ),
                "severity": "medium",
            })

    cols = list(df.columns)
    for col_a, col_b in combinations(cols, 2):
        key = tuple(sorted([col_a, col_b]))
        if key in already_flagged:
            continue
        try:
            if df[col_a].astype(str).equals(df[col_b].astype(str)):
                already_flagged.add(key)
                issues.append({
                    "column": f"{col_a} / {col_b}",
                    "type": "duplicate_columns",
                    "detail": (
                        f"Columns '{col_a}' and '{col_b}' are identical "
                        f"(deterministic value-equality check)"
                    ),
                    "severity": "medium",
                })
        except Exception:
            continue

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
    """Detect extreme values in numerical columns using the IQR fence rule.

    Uses 3 × IQR (Tukey outer fence) rather than 3-sigma so that detection
    is robust to skewed distributions and is not inflated by the very outliers
    it is trying to find.  The 3-sigma rule assumes normality; for right-skewed
    quantities (revenue, hours, prices) it routinely flags perfectly normal
    high-end values.
    """
    issues = []
    for col in numerical_cols:
        if not _has_column(df, col):
            continue
        numeric = _coerce_numeric(df[col], dropna=True)
        if len(numeric) < 10:
            continue
        q1, q3 = numeric.quantile(0.25), numeric.quantile(0.75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        lower = q1 - 3.0 * iqr
        upper = q3 + 3.0 * iqr
        outliers = int(((numeric < lower) | (numeric > upper)).sum())
        if outliers > 0:
            issues.append({
                "column": col,
                "type": "outliers",
                "detail": (
                    f"{outliers} values outside the 3×IQR outer fence "
                    f"[{lower:.2f}, {upper:.2f}]"
                ),
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
    if not _has_column(df, col):
        return []
    numeric = _coerce_numeric(df[col])
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
    if not _has_column(df, col):
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
    severity = _severity_from_rate(pct)
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
    if not _has_column(df, col):
        return []
    nev = non_empty_values(df[col])
    non_numeric_mask = _coerce_numeric(nev).isna()
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
        if not _has_column(df, col):
            continue
        numeric = _coerce_numeric(df[col], dropna=True)
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


_MONTH_ABBR: dict[str, int] = {
    # English
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    # Italian
    "gen": 1, "mag": 5, "giu": 6, "lug": 7, "ago": 8,
    "set": 9, "ott": 10, "dic": 12,
}

_MONTH_FULL_NAMES: dict[str, int] = {
    # Italian
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
    "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
    "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    # English
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Combined lookup: abbreviations + full names
_ALL_MONTH_NAMES: dict[str, int] = {**_MONTH_ABBR, **_MONTH_FULL_NAMES}

# Ordered list of (format_label, compiled_regex) used for period detection
_PERIOD_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("YYYYMM",   re.compile(r"^\d{6}(?:\.0+)?$")),
    ("YYYY-MM",  re.compile(r"^\d{4}-\d{2}$")),
    ("MON-YYYY", re.compile(r"^[A-Za-z]{3}-\d{4}$")),
    ("MM/YYYY",  re.compile(r"^\d{1,2}/\d{4}$")),
    ("TEXT_YYYY",re.compile(r"^[A-Za-z].*\s\d{4}$")),
]


def _parse_period_value(v: str):
    """Convert any recognised period format to canonical MM-YYYY string.

    Supported inputs
    ----------------
    1. YYYYMM          — ``202402``, ``202402.0``
    2. YYYY-MM         — ``2024-06``
    3. MON-YYYY        — ``APR-2024``, ``apr-2024``
    4. MM/YYYY         — ``05/2024``, ``5/2024``
    5. Text + year     — ``Rata 2024``  (month unknown → returns None)

    Returns the canonical MM-YYYY string (e.g. ``"06-2024"``) or ``None`` if the
    value cannot be mapped to a valid year-month pair.
    """
    v = v.strip()

    # 1. YYYYMM (with optional float .0 suffix)
    m = re.match(r"^(\d{6})(?:\.0+)?$", v)
    if m:
        code = m.group(1)
        year, month = int(code[:4]), int(code[4:])
        if 1900 <= year <= 2099 and 1 <= month <= 12:
            return f"{month:02d}-{year}"
        return None

    # 2. YYYY-MM
    m = re.match(r"^(\d{4})-(\d{2})$", v)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        if 1900 <= year <= 2099 and 1 <= month <= 12:
            return f"{month:02d}-{year}"
        return None

    # 3. MON-YYYY  (e.g. APR-2024)
    m = re.match(r"^([A-Za-z]{3})-(\d{4})$", v)
    if m:
        abbr = m.group(1).lower()
        year = int(m.group(2))
        month = _MONTH_ABBR.get(abbr)
        if month and 1900 <= year <= 2099:
            return f"{month:02d}-{year}"
        return None

    # 4. MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{4})$", v)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        if 1900 <= year <= 2099 and 1 <= month <= 12:
            return f"{month:02d}-{year}"
        return None

    # 5. Free text with year only (e.g. "Rata 2024") — month unknowable
    if re.match(r"^[A-Za-z].*\s\d{4}$", v):
        return None

    return None


def check_period_formats(df: pd.DataFrame, categorical_cols: list) -> list:
    """Detect categorical columns that are period codes with inconsistent or
    non-canonical formats across rows.

    A column is considered a *period column* if ≥ 80 % of its non-null values
    match at least one of the recognised period patterns.  An issue is raised
    when more than one distinct format is found, or when any value cannot be
    normalised to YYYYMM.

    Returns issues of type ``'period_format_inconsistency'``.
    """
    issues = []
    for col in categorical_cols:
        if col not in df.columns:
            continue
        nev = non_empty_values(df[col]).astype(str).str.strip()
        if len(nev) < 5:
            continue

        # Count how many values match each period pattern
        format_hits: dict[str, int] = {label: 0 for label, _ in _PERIOD_PATTERNS}
        total_matched = 0
        for val in nev:
            for label, pat in _PERIOD_PATTERNS:
                if pat.match(val):
                    format_hits[label] += 1
                    total_matched += 1
                    break

        period_coverage = total_matched / len(nev)
        if period_coverage < 0.80:
            continue  # not a period column

        active_formats = [lbl for lbl, cnt in format_hits.items() if cnt > 0]
        n_formats = len(active_formats)
        unparseable = int(
            nev.apply(lambda v: _parse_period_value(v) is None).sum()
        )
        pct_unparseable = unparseable / len(nev)

        if n_formats > 1 or unparseable > 0:
            severity = "high" if pct_unparseable > 0.05 else "medium"
            issues.append({
                "column": col,
                "type": "period_format_inconsistency",
                "detail": (
                    f"{n_formats} period format(s) detected "
                    f"({', '.join(active_formats)}); "
                    f"{unparseable} value(s) ({pct_unparseable:.1%}) "
                    f"cannot be normalised to YYYYMM"
                ),
                "severity": severity,
            })

    return issues


def normalize_period_column(df: pd.DataFrame, col: str) -> tuple[int, int]:
    """Normalise all period values in *col* to canonical YYYYMM strings in-place.

    Values that cannot be parsed (unknown format, invalid month/year) are set
    to ``pd.NA``.

    Returns ``(n_normalised, n_nulled)``.
    """
    if col not in df.columns:
        return 0, 0

    original = df[col].copy()

    def _convert(v):
        if pd.isna(v) or str(v).strip() == "":
            return v
        result = _parse_period_value(str(v).strip())
        return result if result is not None else pd.NA

    df[col] = original.apply(_convert)

    n_nulled = int((df[col].isna() & original.notna() &
                    (original.astype(str).str.strip() != "")).sum())
    n_normalised = int(
        (df[col].notna() & (df[col].astype(str) != original.astype(str))).sum()
    )
    return n_normalised, n_nulled


def check_placeholder_values(df: pd.DataFrame) -> list:
    """Detect individual cells containing known placeholder strings in any column,
    regardless of overall missing rate.

    Unlike compute_completeness (which has a >5% threshold), this function reports
    columns with even a single placeholder cell, enabling surgical remediation.
    """
    issues = []
    for col in df.columns:
        s = df[col].astype(str).str.strip().str.lower()
        placeholder_mask = s.isin(PLACEHOLDERS)
        count = int(placeholder_mask.sum())
        if count == 0:
            continue
        pct = count / len(df)
        severity = _severity_from_rate(pct)
        issues.append({
            "column": col,
            "type": "placeholder_values",
            "detail": (
                f"{count} cells contain known placeholder strings "
                f"(e.g. '-', '//', '?', 'n.d.') that should be NULL"
            ),
            "severity": severity,
            "rows_affected": count,
        })
    return issues


# Special month codes that represent unknowns or annual aggregates, not real months
_SPECIAL_MONTH_CODES = frozenset({-1, 0, 13, 99})


def _is_month_column(df: pd.DataFrame, col: str) -> bool:
    """Return True when col looks like a standalone month column.

    A column qualifies when ≥ 80 % of its non-null values can be resolved to a
    month number (integers 1-12 + special codes, or recognisable text names).
    """
    if col not in df.columns:
        return False
    raw = df[col].dropna()
    if len(raw) < 5:
        return False
    resolved = 0
    for v in raw.astype(str).str.strip():
        lower = v.lower()
        if lower in _ALL_MONTH_NAMES:
            resolved += 1
            continue
        try:
            n = float(v)
            if n % 1 == 0 and int(n) in (set(range(-1, 14)) | {99}):
                resolved += 1
        except (ValueError, TypeError):
            pass
    return resolved / len(raw) >= 0.80


def check_month_column(df: pd.DataFrame, cols: list) -> list:
    """Detect standalone month columns and flag two classes of problems:

    * ``'special_month_code'`` — integer codes -1, 0, 13, 99 (unknowns / annual
      aggregates) that should become NULL or a dedicated category.
    * ``'month_format_inconsistency'`` — text month names (e.g. ``'Settembre'``,
      ``'September'``) mixed with or instead of the canonical integer form.

    A column is identified as a month column by ``_is_month_column``.
    """
    issues = []
    for col in cols:
        if not _is_month_column(df, col):
            continue

        raw = df[col].dropna().astype(str).str.strip()

        # --- text month names ---
        text_months = [v for v in raw if v.lower() in _ALL_MONTH_NAMES
                       and not v.lstrip("-").replace(".", "").isdigit()]
        n_text = len(text_months)
        if n_text > 0:
            pct = n_text / len(raw)
            issues.append({
                "column": col,
                "type": "month_format_inconsistency",
                "detail": (
                    f"{n_text} values ({pct:.1%}) are text month names "
                    f"(e.g. '{text_months[0]}') — should be integers 1-12"
                ),
                "severity": "medium" if pct > 0.05 else "low",
            })

        # --- special integer codes ---
        numeric = _coerce_numeric(df[col], dropna=True)
        int_vals = numeric[numeric % 1 == 0].astype(int)
        special_mask = int_vals.isin(_SPECIAL_MONTH_CODES)
        n_special = int(special_mask.sum())
        if n_special > 0:
            special_vals = sorted(int_vals[special_mask].unique().tolist())
            pct = n_special / len(raw)
            issues.append({
                "column": col,
                "type": "special_month_code",
                "detail": (
                    f"{n_special} values ({pct:.1%}) are special month codes "
                    f"{special_vals} — likely unknowns or annual aggregates; "
                    f"should be NULL or a dedicated category"
                ),
                "severity": "medium" if pct > 0.05 else "low",
            })
    return issues


def check_year_column(df: pd.DataFrame, cols: list) -> list:
    """Detect columns that behave like standalone 4-digit year columns and flag:

    * ``'year_format_inconsistency'`` — dirty strings like ``'2024.'`` that can
      be cleaned deterministically.
    * ``'ambiguous_year_format'`` — 2-digit year values whose century can be
      inferred from the dominant year in the column.
    * ``'invalid_year_value'`` — values outside [1900, 2099] that need manual
      review.

    A column is identified as a year column when ≥ 80 % of values parse to valid
    4-digit years after stripping trailing non-digit noise.
    """
    issues = []
    for col in cols:
        if not _has_column(df, col):
            continue
        raw = df[col].dropna().astype(str).str.strip()
        if len(raw) < 5:
            continue

        # Strip trailing non-digit characters for detection only
        cleaned = raw.str.replace(r"[^\d]$", "", regex=True)
        numeric = _coerce_numeric(cleaned, dropna=True)
        if len(numeric) == 0:
            continue
        int_vals = numeric[numeric % 1 == 0].astype(int)
        in_range = ((int_vals >= 1900) & (int_vals <= 2099)).sum()
        if in_range / len(int_vals) < 0.80:
            continue  # not a year column

        # Count values that have trailing non-digit noise (e.g. "2024.")
        dirty_mask = raw.str.match(r"^\d{4}[^\d]+$")
        n_dirty = int(dirty_mask.sum())
        if n_dirty > 0:
            pct = n_dirty / len(raw)
            issues.append({
                "column": col,
                "type": "year_format_inconsistency",
                "detail": (
                    f"{n_dirty} values ({pct:.1%}) have trailing non-digit "
                    f"characters (e.g. '2024.') — can be cleaned automatically"
                ),
                "severity": "low",
            })

        # 2-digit years (auto-fixable via century inference)
        two_digit_mask = (int_vals >= 0) & (int_vals <= 99)
        n_two = int(two_digit_mask.sum())
        if n_two > 0:
            pct = n_two / len(int_vals)
            issues.append({
                "column": col,
                "type": "ambiguous_year_format",
                "detail": (
                    f"{n_two} values ({pct:.1%}) appear to be 2-digit years "
                    f"— century will be inferred from the dominant year in the column"
                ),
                "severity": "medium",
            })

        # Truly out-of-range (not 2-digit, not dirty trailing)
        out_of_range = int(
            ((int_vals < 1900) | (int_vals > 2099)).sum()
        ) - n_two
        if out_of_range > 0:
            pct = out_of_range / len(int_vals)
            issues.append({
                "column": col,
                "type": "invalid_year_value",
                "detail": (
                    f"{out_of_range} values ({pct:.1%}) fall outside the valid "
                    f"year range [1900-2099]"
                ),
                "severity": "medium",
            })
    return issues


def fix_month_column(df: pd.DataFrame, col: str) -> int:
    """Normalise a standalone month column to integers 1-12 in-place.

    * Text month names (``'Settembre'``, ``'September'``, abbreviations) are
      converted to their integer equivalent.
    * Valid integers 1-12 are left as-is (cast to int).
    * Special codes (-1, 0, 13, 99) are set to NULL.
    * Anything else unrecognisable is set to NULL.

    Returns the number of cells changed (converted + nulled).
    """
    if col not in df.columns:
        return 0
    changed = 0
    for idx, raw in df[col].items():
        if pd.isna(raw) or str(raw).strip() == "":
            continue
        v = str(raw).strip()
        lower = v.lower()

        # Text month name
        if lower in _ALL_MONTH_NAMES:
            new_val = _ALL_MONTH_NAMES[lower]
            if str(raw) != str(new_val):
                df.at[idx, col] = new_val
                changed += 1
            continue

        # Numeric
        try:
            n = float(v)
        except (ValueError, TypeError):
            df.at[idx, col] = pd.NA
            changed += 1
            continue

        if n % 1 != 0:
            df.at[idx, col] = pd.NA
            changed += 1
            continue

        int_n = int(n)
        if int_n in _SPECIAL_MONTH_CODES:
            df.at[idx, col] = pd.NA
            changed += 1
        elif 1 <= int_n <= 12:
            if str(raw) != str(int_n):
                df.at[idx, col] = int_n
                changed += 1
        else:
            df.at[idx, col] = pd.NA
            changed += 1

    return changed


def fix_year_column(df: pd.DataFrame, col: str) -> int:
    """Normalise a standalone year column to 4-digit integers in-place.

    * Trailing non-digit noise is stripped (``'2024.'`` → ``2024``).
    * 2-digit years are expanded using the century of the most frequent
      valid 4-digit year already in the column (e.g. ``'23'`` → ``2023``
      when the dominant year is ``2023``).
    * Values that cannot be resolved to a valid year are set to NULL.

    Returns the number of cells changed.
    """
    if col not in df.columns:
        return 0

    # Infer the century prefix from the dominant 4-digit year
    four_digit = pd.to_numeric(
        df[col].dropna().astype(str).str.strip()
               .str.replace(r"[^\d]$", "", regex=True),
        errors="coerce"
    ).dropna()
    four_digit = four_digit[(four_digit >= 1900) & (four_digit <= 2099)]
    century_prefix = int(four_digit.mode().iloc[0]) // 100 * 100 if len(four_digit) > 0 else 2000

    changed = 0
    for idx, raw in df[col].items():
        if pd.isna(raw) or str(raw).strip() == "":
            continue
        v = str(raw).strip()

        # Strip trailing non-digit characters
        v_clean = re.sub(r"[^\d]+$", "", v)
        if not v_clean:
            df.at[idx, col] = pd.NA
            changed += 1
            continue

        try:
            n = int(v_clean)
        except ValueError:
            df.at[idx, col] = pd.NA
            changed += 1
            continue

        # Expand 2-digit year
        if 0 <= n <= 99:
            n = century_prefix + n

        if 1900 <= n <= 2099:
            if str(raw) != str(n):
                df.at[idx, col] = n
                changed += 1
        else:
            df.at[idx, col] = pd.NA
            changed += 1

    return changed


def fix_special_month_codes(df: pd.DataFrame, col: str) -> int:
    """Null out special month codes (-1, 0, 13, 99) in a standalone month column.

    These codes typically encode unknowns or annual aggregates and should not be
    treated as valid calendar months.  Returns the number of cells nulled.
    """
    if not _has_column(df, col):
        return 0
    numeric = _coerce_numeric(df[col])
    mask = numeric.isin(_SPECIAL_MONTH_CODES)
    count = int(mask.sum())
    if count > 0:
        df.loc[mask, col] = pd.NA
    return count


def check_fractional_integers(
    df: pd.DataFrame, numerical_cols: list, threshold: float = 0.80
) -> list:
    """Detect numerical columns where almost all values are whole numbers but
    a minority have non-trivial fractional parts — a sign of data corruption.

    Returns issues of type 'fractional_integers' for affected columns.
    """
    issues = []
    for col in numerical_cols:
        if not _has_column(df, col):
            continue
        numeric = _coerce_numeric(df[col], dropna=True)
        if len(numeric) < 5:
            continue
        whole = (numeric % 1 == 0).sum()
        whole_frac = whole / len(numeric)
        if whole_frac < threshold:
            continue
        fractional_mask = (numeric % 1 != 0) & ((numeric % 1).abs() > 1e-9)
        n_fractional = int(fractional_mask.sum())
        if n_fractional == 0:
            continue
        pct = n_fractional / len(numeric)
        issues.append({
            "column": col,
            "type": "fractional_integers",
            "detail": (
                f"{n_fractional} values ({pct:.1%}) have non-zero fractional "
                f"parts in a column where {whole_frac:.0%} of values are "
                f"whole numbers — likely corrupted entries"
            ),
            "severity": "high" if pct > 0.02 else "medium",
        })
    return issues


# ── Remediation ────────────────────────────────────────────────────────────────

def fix_fractional_integers(df: pd.DataFrame, col: str) -> int:
    """Set values with non-trivial fractional parts to NaN in-place for a
    column that should contain only whole numbers.

    Returns the number of values nulled.
    """
    if not _has_column(df, col):
        return 0
    numeric = _coerce_numeric(df[col])
    fractional_mask = (numeric % 1 != 0) & ((numeric % 1).abs() > 1e-9)
    count = int(fractional_mask.sum())
    if count > 0:
        df.loc[fractional_mask, col] = np.nan
    return count


def round_float_precision(df: pd.DataFrame, col: str, decimals: int = 2) -> int:
    """Round a numerical column to *decimals* places in-place to remove
    floating-point arithmetic noise.

    Returns the number of values changed.
    """
    if not _has_column(df, col):
        return 0
    numeric = _coerce_numeric(df[col])
    rounded = numeric.round(decimals)
    changed = int((numeric != rounded).sum())
    if changed > 0:
        df[col] = rounded
    return changed


def null_pattern_violations(df: pd.DataFrame, col: str, pattern: str) -> int:
    """Set values that do not match *pattern* to NaN in-place.

    Safety guard: if more than 30% of non-empty values would be nulled the
    pattern is likely wrong (e.g. an LLM-inferred regex that excludes a valid
    value class such as "0" in a binary flag).  In that case no changes are
    made and 0 is returned so the issue is treated as flagged-for-review.

    Returns the number of values nulled.
    """
    if col not in df.columns:
        return 0
    nev_mask = ~missing_mask(df[col])
    nev_count = int(nev_mask.sum())
    if nev_count == 0:
        return 0
    try:
        compiled = re.compile(pattern)
    except re.error:
        return 0
    violates = nev_mask & df[col].astype(str).apply(
        lambda v: not compiled.match(str(v))
    )
    count = int(violates.sum())
    # Safety guard: refuse to null more than 30% of non-empty values
    if nev_count > 0 and count / nev_count > 0.30:
        return 0
    if count > 0:
        df.loc[violates, col] = np.nan
    return count


def fix_mixed_type(df: pd.DataFrame, col: str) -> int:
    """Coerce column to numeric in-place. Returns number of values that became NaN."""
    if not _has_column(df, col):
        return 0
    before_na = int(df[col].isna().sum())
    df[col] = _coerce_numeric(df[col])
    return int(df[col].isna().sum()) - before_na


def fix_invalid_dates(df: pd.DataFrame, col: str) -> tuple[str, int]:
    """Re-parse a date column choosing the best dayfirst setting in-place.

    Detects YYYYMM period-code columns and handles them without converting to
    datetime (pd.to_datetime cannot parse YYYYMM without an explicit format and
    would null every value). For YYYYMM columns, invalid entries are nulled and
    the valid integer codes are preserved as-is.

    Returns (method_used, valid_count).
    """
    if col not in df.columns:
        return "", 0

    # Detect YYYYMM period codes: strip optional .0 suffix and check pattern
    clean = df[col].astype(str).str.strip().str.replace(r"\.0+$", "", regex=True)
    yyyymm_frac = clean.apply(
        lambda v: bool(re.match(r"^\d{6}$", v))
        and 1 <= int(v[4:]) <= 12
        and int(v[:4]) >= 1900
        if re.match(r"^\d{6}$", v) else False
    ).mean()
    if yyyymm_frac > 0.80:
        valid_mask = clean.apply(
            lambda v: bool(re.match(r"^\d{6}$", v))
            and 1 <= int(v[4:]) <= 12
            and int(v[:4]) >= 1900
            if re.match(r"^\d{6}$", v) else False
        )
        df[col] = clean.where(valid_mask, other=pd.NA)
        return "YYYYMM_validated", int(valid_mask.sum())

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
    if not _has_column(df, col):
        return False, "Column not found"
    numeric = _coerce_numeric(df[col])
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

    Only auto-imputes for low severity (< 20% missing).  Medium and high
    severity columns are flagged rather than filled: mode imputation on large
    missing fractions distorts the distribution and masks real data problems.
    Returns (success, detail_message).
    """
    if col not in df.columns:
        return False, "Column not found"
    rows_affected = int(is_missing.sum())
    if severity in ("high", "medium"):
        return False, (
            f"Categorical column with {rows_affected} missing values "
            f"(severity={severity}): mode imputation suppressed to prevent "
            f"distribution distortion — flagged for domain review"
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
    """Clip outliers in col to the 3×IQR outer fence derived from raw_series.

    Uses the interquartile range (Tukey outer fence = Q1 − 3×IQR, Q3 + 3×IQR)
    instead of mean ± 3σ.  IQR-based bounds are resistant to the influence of
    the very outliers being capped, which makes them appropriate for skewed
    distributions such as revenue, hours, or prices.

    Returns (lower, upper, count_capped). Returns (0, 0, 0) if not applicable.
    """
    if not _has_column(df, col):
        return 0.0, 0.0, 0
    raw_valid = _coerce_numeric(raw_series, dropna=True)
    if len(raw_valid) < 4:
        return 0.0, 0.0, 0
    q1, q3 = raw_valid.quantile(0.25), raw_valid.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return 0.0, 0.0, 0
    lower, upper = q1 - 3.0 * iqr, q3 + 3.0 * iqr
    numeric = _coerce_numeric(df[col])
    count = int(((numeric < lower) | (numeric > upper)).sum())
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
    """Normalize case variants and single-character typos in a categorical column.

    Two-pass strategy:
    1. Case normalization — map every value to the most-frequent casing of its
       lowercase form (e.g. 'seo', 'SEO', 'Seo' → 'SEO').
    2. Typo correction — for rare values (< 1% of non-empty rows) that are not
       already covered by step 1, find the closest frequent canonical via
       SequenceMatcher and apply the correction when the similarity ratio is
       above 0.85.  This fixes single-character insertions/deletions such as
       'Contennt' → 'Content' or 'Desgn' → 'Design' without touching
       legitimately distinct rare categories.

    Returns number of values changed.
    """
    from difflib import SequenceMatcher

    if col not in df.columns:
        return 0

    original = df[col].copy()
    non_empty_mask = df[col].notna() & (df[col].astype(str).str.strip() != "")
    stripped = df[col].astype(str).str.strip()
    value_counts = stripped[non_empty_mask].value_counts()
    total = int(value_counts.sum())
    if total == 0:
        return 0

    # Step 1: build the canonical (most-frequent) casing for each lowercase form
    lower_to_canonical: dict[str, str] = {}
    for val in value_counts.index:
        key = val.lower()
        if key not in lower_to_canonical:
            lower_to_canonical[key] = val  # first = most frequent

    # Frequent canonical lowercase forms (>= 1% of rows) — reference for fuzzy
    frequent_lowers = [
        val.lower()
        for val, cnt in value_counts.items()
        if cnt / total >= 0.01
    ]

    # Build the replacement map
    replacement: dict[str, str] = {}

    for raw_val, cnt in value_counts.items():
        lower_val = raw_val.lower()

        # Case normalization
        canonical = lower_to_canonical.get(lower_val)
        if canonical and canonical != raw_val:
            replacement[raw_val] = canonical
            continue

        # Typo correction for rare values not resolved by case normalization
        if cnt / total < 0.01 and raw_val not in replacement:
            best_match: str | None = None
            best_ratio = 0.84  # similarity threshold
            for fl in frequent_lowers:
                ratio = SequenceMatcher(None, lower_val, fl).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match = fl
            if best_match:
                replacement[raw_val] = lower_to_canonical[best_match]

    if not replacement:
        # Still apply strip-only normalisation so trailing spaces are removed
        df.loc[non_empty_mask, col] = stripped[non_empty_mask]
        return int((df[col] != original).sum())

    normalized = stripped.map(lambda v: replacement.get(v, v))
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
    if new_name and new_name[0].isdigit():
        new_name = f"col_{new_name}"
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


# ── Code validation ────────────────────────────────────────────────────────────

import ast as _ast

_ALLOWED_IMPORTS = {"pandas", "numpy", "re", "math"}
_FORBIDDEN_CALLS = {"exec", "eval", "open", "compile", "__import__"}
_FORBIDDEN_ATTRS = {"remove", "rmdir", "system", "popen", "unlink", "rmtree",
                    "call", "run", "Popen"}


def validate_generated_code(code: str) -> tuple[bool, str]:
    """AST-level validation for LLM-generated fix functions.

    Checks for forbidden imports and dangerous calls before the code
    is passed to the subprocess sandbox.  Returns (is_valid, reason).
    """
    try:
        tree = _ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in _ALLOWED_IMPORTS:
                    return False, f"Forbidden import: {alias.name}"

        if isinstance(node, _ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in _ALLOWED_IMPORTS:
                return False, f"Forbidden import: {node.module}"

        if isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Name):
                if node.func.id in _FORBIDDEN_CALLS:
                    return False, f"Forbidden call: {node.func.id}"
            if isinstance(node.func, _ast.Attribute):
                if node.func.attr in _FORBIDDEN_ATTRS:
                    return False, f"Forbidden attribute call: .{node.func.attr}"

    return True, "OK"


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
