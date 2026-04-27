"""Layer 3 remediation agent. Applies automated fixes for data quality issues
identified by Layer 1 agents, logs all actions to the fix log, and uses LLM
reasoning for ambiguous remediation decisions.
"""

from collections import defaultdict

import pandas as pd

from agents_demo.base_agent import SMART, BaseAgent
from agents_demo.code_validator_agent import CodeValidatorAgent
from state_demo.constants import GAP_DETECTION_ISSUE_TYPES, ISSUE_TYPES, PLACEHOLDERS, SEVERITY_RANK
from state_demo.helpers import missing_mask, non_empty_values
from tools import (
    _is_placeholder_series,
    apply_lookup_imputation,
    build_column_lookup,
    cap_outliers,
    fill_missing_categorical,
    fill_missing_numerical,
    fix_column_naming,
    fix_fractional_integers,
    fix_invalid_dates,
    fix_mixed_type,
    fix_month_column,
    fix_year_column,
    normalize_case,
    normalize_period_column,
    null_pattern_violations,
    pick_duplicate_column_to_drop,
    remove_duplicate_rows,
    round_float_precision,
    standardize_date_format,
)


class RemediationAgent(BaseAgent):
    name = "remediation"
    model = SMART

    INSTRUCTION = (
        "You are a data quality remediation specialist. You plan and apply "
        "automated fixes for data quality issues, making conservative decisions "
        "that preserve data integrity. For ambiguous missing-value cases, you "
        "recommend the best imputation strategy."
    )

    def think(self):
        issues = self.state.prioritized_issues
        insights = self.state.cross_agent_insights
        auto_types = {
            "duplicate_rows",
            "outliers",
            "mixed_type",
            "naming_convention",
            "format_inconsistency",
            "case_inconsistency",
            "missing_values",
            "invalid_dates",
            "float_precision_noise",
            "fractional_integers",
            "format_pattern_violation",
            "placeholder_values",
            "period_format_inconsistency",
            "special_month_code",
            "month_format_inconsistency",
            "ambiguous_year_format",
            "year_format_inconsistency",
        }
        auto_count = sum(1 for i in issues if i["type"] in auto_types)
        flag_count = len(issues) - auto_count
        self.log(
            "think",
            f"{self.prompt} | Planning remediation for {len(issues)} issues "
            f"({auto_count} auto-fixable, {flag_count} flag-only). "
            f"{len(insights)} cross-agent insights available.",
        )

    def act(self):
        df = self.state.df_raw.copy()
        fp = self.state.dataset_fingerprint
        id_cols = set(fp.get("id_columns", []))
        cat_cols = set(fp.get("categorical_columns", []))

        issues_by_type: dict = defaultdict(list)
        for issue in self.state.prioritized_issues:
            issues_by_type[issue["type"]].append(issue)

        for issue in issues_by_type.get("period_format_inconsistency", []):
            col = issue["column"]
            normalised, nulled = normalize_period_column(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Normalised {normalised} period values to canonical "
                f"YYYYMM format; {nulled} unparseable values set to NULL",
                normalised + nulled,
            )

        # Merge month_format_inconsistency + special_month_code into one fix pass
        # (fix_month_column handles text names, specials, and out-of-range in one go)
        month_cols_fixed = set()
        for issue in issues_by_type.get("month_format_inconsistency", []) + issues_by_type.get(
            "special_month_code", []
        ):
            col = issue["column"]
            if col in month_cols_fixed:
                continue
            month_cols_fixed.add(col)
            changed = fix_month_column(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Normalised {changed} month values to integers 1-12 "
                f"(converted text names, nulled special codes)",
                changed,
            )

        # Year column normalisation: trailing noise + 2-digit century expansion
        year_cols_fixed = set()
        for issue in issues_by_type.get("year_format_inconsistency", []) + issues_by_type.get(
            "ambiguous_year_format", []
        ):
            col = issue["column"]
            if col in year_cols_fixed:
                continue
            year_cols_fixed.add(col)
            changed = fix_year_column(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Normalised {changed} year values to 4-digit integers "
                f"(stripped trailing noise, expanded 2-digit years)",
                changed,
            )

        for issue in issues_by_type.get("placeholder_values", []):
            col = issue["column"]
            if col not in df.columns:
                continue
            # Use combined exact-match + regex detection so that values like
            # 'da verificare', 'imposta x', or whitespace-only cells are caught.
            placeholder_mask = _is_placeholder_series(df[col])
            count = int(placeholder_mask.sum())
            if count > 0:
                df.loc[placeholder_mask, col] = None
                self._log_fix(
                    issue, "auto_fixed", f"Replaced {count} placeholder cells with NULL", count
                )

        for issue in issues_by_type.get("fractional_integers", []):
            col = issue["column"]
            nulled = fix_fractional_integers(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Nulled {nulled} values with non-trivial fractional parts in integer column",
                nulled,
            )

        for issue in issues_by_type.get("mixed_type", []):
            col = issue["column"]
            coerced = fix_mixed_type(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Coerced to numeric -- {coerced} non-numeric values became NaN",
                coerced,
            )

        for issue in issues_by_type.get("invalid_dates", []):
            col = issue["column"]
            method, valid = fix_invalid_dates(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Re-parsed dates ({method}) -- {valid}/{len(df)} values parsed successfully",
                valid,
            )

        if issues_by_type.get("duplicate_rows"):
            removed = remove_duplicate_rows(df)
            df.reset_index(drop=True, inplace=True)
            self._log_fix(
                {"type": "duplicate_rows", "column": "_rows_"},
                "auto_fixed",
                f"Removed {removed} duplicate rows (kept first occurrence)",
                removed,
            )

        for issue in issues_by_type.get("missing_values", []):
            self._fix_missing_values(df, issue, fp)

        for issue in issues_by_type.get("outliers", []):
            col = issue["column"]
            if col in id_cols:
                self._log_fix(
                    issue,
                    "flagged_for_review",
                    "Outlier in ID/key column — "
                    "capping would corrupt semantics, requires manual review",
                    0,
                )
                continue

            # Guard: never cap columns the profiler classified as categorical —
            # they contain codes or enums, not continuous quantities.
            if col in cat_cols:
                self._log_fix(
                    issue,
                    "flagged_for_review",
                    "Column classified as categorical (codes/enums) — "
                    "outlier capping suppressed to preserve category integrity",
                    0,
                )
                continue

            # Guard: don't cap power-law / highly-skewed distributions.
            # Financial amounts, counts, and similar data follow power-law
            # distributions where the top decile represents real, valid entities
            # (large ministries, high-spending departments).  Capping them with
            # a fixed fence destroys the data and biases every downstream metric.
            raw_numeric = pd.to_numeric(self.state.df_raw[col], errors="coerce").dropna()
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
                    self._log_fix(
                        issue,
                        "flagged_for_review",
                        f"Skewed distribution (skewness={skewness:.2f}, "
                        f"{cap_rate:.1%} of values beyond 3×IQR fence) — "
                        f"capping suppressed to preserve power-law structure; "
                        f"use log-transform or domain-specific bounds instead",
                        0,
                    )
                    continue

            lower, upper, count = cap_outliers(df, col, self.state.df_raw[col])
            if count > 0:
                self._log_fix(
                    issue,
                    "auto_fixed",
                    f"Capped {count} outliers to [{lower:.2f}, {upper:.2f}] (3×IQR fence)",
                    count,
                )

        for issue in issues_by_type.get("float_precision_noise", []):
            col = issue["column"]
            changed = round_float_precision(df, col, decimals=2)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Rounded {changed} values to 2 decimal places to remove floating-point noise",
                changed,
            )

        for issue in issues_by_type.get("format_pattern_violation", []):
            col = issue.get("column", "")
            pattern = issue.get("pattern", "")
            # Never auto-null values in ID or key columns based on a pattern —
            # an incorrect LLM-inferred regex would destroy the primary key.
            if col in id_cols or col in fp.get("suggested_key_columns", []):
                self._log_fix(
                    issue,
                    "flagged_for_review",
                    f"Format pattern violation in ID/key column "
                    f"'{col}' — auto-nulling suppressed to preserve "
                    f"primary key integrity",
                    0,
                )
            elif pattern:
                nulled = null_pattern_violations(df, col, pattern)
                self._log_fix(
                    issue,
                    "auto_fixed",
                    f"Nulled {nulled} values violating expected format pattern",
                    nulled,
                )
            else:
                self._flag_issue(issue)

        for issue in issues_by_type.get("format_inconsistency", []):
            col = issue.get("column", "")
            action, detail = standardize_date_format(df, col)
            self._log_fix(issue, action, detail, 0 if action == "flagged_for_review" else 1)

        for issue in issues_by_type.get("case_inconsistency", []):
            col = issue.get("column", "")
            changed = normalize_case(df, col)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Normalized {changed} values to most frequent casing variant",
                changed,
            )

        # Drop duplicate columns BEFORE renaming so the original names
        # detected by DuplicateAgent still exist in df.
        dropped_cols: set = set()
        for issue in issues_by_type.get("duplicate_columns", []):
            raw = issue.get("column", "")
            parts = [c.strip() for c in raw.split("/")]
            if len(parts) != 2:
                self._flag_issue(issue)
                continue
            col_a, col_b = parts
            # skip if either column was already dropped by a previous iteration
            if col_a not in df.columns or col_b not in df.columns:
                continue

            # Value-domain guard: if the two columns have different value spaces
            # (e.g. numeric codes vs text descriptions) they are complementary,
            # not structural duplicates — skip the drop regardless of the issue source.
            # Placeholder values are excluded so shared sentinels (n.d., -, ?) don't
            # inflate the similarity score.
            def _content(col):
                vals = df[col].dropna().astype(str).str.strip()
                return {
                    v
                    for v in vals
                    if v and v.lower() not in PLACEHOLDERS and not all(c in r"-./?#\/ " for c in v)
                }

            set_a = _content(col_a)
            set_b = _content(col_b)
            if set_a and set_b:
                jaccard = len(set_a & set_b) / len(set_a | set_b)
                if jaccard < 0.20:
                    self._log_fix(
                        issue,
                        "flagged_for_review",
                        f"Skipped drop of '{col_a}'/'{col_b}': "
                        f"value-domain Jaccard={jaccard:.2f} — columns are complementary",
                        0,
                    )
                    continue
            to_drop = pick_duplicate_column_to_drop(col_a, col_b)
            to_keep = col_b if to_drop == col_a else col_a
            if to_drop in dropped_cols:
                continue
            df.drop(columns=[to_drop], inplace=True)
            dropped_cols.add(to_drop)
            self._log_fix(
                issue,
                "auto_fixed",
                f"Dropped duplicate column '{to_drop}' (kept '{to_keep}')",
                0,
            )

        for issue in issues_by_type.get("naming_convention", []):
            col = issue["column"]
            if col not in df.columns:
                # column was already dropped as a duplicate — skip rename
                continue
            old, new = fix_column_naming(df, col)
            if new != old:
                self._log_fix(
                    issue, "auto_fixed", f"Renamed '{old}' -> '{new}'", 0, old=old, new=new
                )

        # Duplicate-key on id_columns: rows with the same primary key value
        # are a data integrity violation — drop subsequent duplicates (keep first).
        # Non-id-column key collisions are flagged for domain review.
        for issue in issues_by_type.get("duplicate_key", []):
            key_cols = [c.strip() for c in issue["column"].split(",") if c.strip() in df.columns]
            if not key_cols:
                continue
            id_key_cols = [c for c in key_cols if c in id_cols]
            if id_key_cols:
                before = len(df)
                df.drop_duplicates(subset=key_cols, keep="first", inplace=True)
                df.reset_index(drop=True, inplace=True)
                removed = before - len(df)
                self._log_fix(
                    issue,
                    "auto_fixed",
                    f"Removed {removed} rows with duplicate primary key "
                    f"[{issue['column']}] (kept first occurrence per key)",
                    removed,
                )
            else:
                self._flag_issue(issue)

        # Lookup-based imputation: fill missing values using cross-column mappings
        # learned from clean (non-null, non-placeholder) rows.
        # Runs AFTER placeholder replacement so that former-placeholder cells
        # (now NULL) are eligible for imputation from their paired columns.
        lookup_filled_total = 0
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
                lookup_filled_total += filled
                self._log_fix(
                    issue,
                    "auto_fixed",
                    f"Imputed {filled} missing '{tgt}' values from '{src}' "
                    f"via learned mapping ({len(lookup)} unique mappings)",
                    filled,
                )
            else:
                self.log("act", f"Lookup imputation for '{tgt}' ← '{src}': 0 rows filled")

        for flag_type in (
            "sparse_column",
            "date_order",
            "rare_categories",
            "conditional_completeness",
            "cross_column_mismatch",
            "domain_negative_values",
            "currency_symbol_in_numeric",
            "comma_decimal_format",
            "nd_placeholder_in_numeric",
            "ambiguous_year_format",
            "invalid_year_value",
        ):
            for issue in issues_by_type.get(flag_type, []):
                col = issue.get("column", "")
                if col and col not in df.columns:
                    # column was already dropped (e.g. as a duplicate) — skip
                    continue
                self._flag_issue(issue)

        self._recompute_additive_derivatives(df, self.state.df_raw)
        self.state.df_cleaned = df

        # Post-remediation gap detection: run on cleaned data so the LLM
        # sees the actual current state, not the original raw values.
        gap_issues = self._run_gap_detection(df)
        for issue in gap_issues:
            self.state.prioritized_issues.append(issue)
        if gap_issues:
            self.log("act", f"Routing {len(gap_issues)} gap issue(s) to CodeValidatorAgent")
            validator = CodeValidatorAgent(self.state)
            validator.run(gap_issues)

    # Keywords that identify "derived" columns (results of arithmetic between
    # other columns).  Only columns whose names contain one of these tokens are
    # candidates for automatic recomputation.  This prevents the algorithm from
    # "correcting" a base measurement (e.g. cost, revenue) using a derived
    # quantity (e.g. profit), which would propagate capping errors incorrectly.
    _DERIVED_KEYWORDS = frozenset(
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

    @classmethod
    def _looks_derived(cls, col_name: str) -> bool:
        lower = col_name.lower()
        return any(kw in lower for kw in cls._DERIVED_KEYWORDS)

    def _recompute_additive_derivatives(self, df_clean, df_raw):
        """Detect and recompute columns derived by subtraction after capping.

        After outlier capping modifies a base column (e.g. revenue), any
        derived column (e.g. profit = revenue − cost) becomes arithmetically
        inconsistent.  This step:

        1. Identifies which numerical columns were capped.
        2. For each *derived-looking* column (name contains keywords like
           "profit", "margin", "net", etc.) that was NOT itself capped, checks
           whether it satisfies col_c ≈ col_a − col_b in the original data
           where col_a is capped and col_b is a base (non-capped) column.
        3. Recomputes col_c = capped_col_a − original_col_b.

        Only derived-named columns are recomputed to avoid accidentally
        overwriting base measurements using arithmetic from derived ones.
        """
        import pandas as pd

        # Which columns were touched by outlier capping?
        capped_cols = {
            f["column"]
            for f in self.state.fix_log
            if f["issue_type"] == "outliers" and f["action"] == "auto_fixed"
        }
        if not capped_cols:
            return

        # Collect numerical columns present in both frames
        num_cols = [
            col
            for col in df_clean.columns
            if col in df_raw.columns
            and pd.to_numeric(df_raw[col], errors="coerce").notna().mean() > 0.80
        ]
        if len(num_cols) < 3:
            return

        recomputed: set = set()
        min_rows = max(10, int(len(df_clean) * 0.50))

        for col_c in num_cols:
            # Only recompute derived-looking columns
            if not self._looks_derived(col_c):
                continue
            if col_c in capped_cols or col_c in recomputed:
                continue
            c_raw = pd.to_numeric(df_raw[col_c], errors="coerce")

            # col_a must be capped; col_b must NOT be capped (to stay stable)
            for col_a in capped_cols:
                if col_a not in num_cols or col_a == col_c:
                    continue
                a_raw = pd.to_numeric(df_raw[col_a], errors="coerce")

                for col_b in num_cols:
                    if col_b in capped_cols or col_b == col_a or col_b == col_c:
                        continue
                    b_raw = pd.to_numeric(df_raw[col_b], errors="coerce")
                    both_valid = c_raw.notna() & a_raw.notna() & b_raw.notna()
                    if both_valid.sum() < min_rows:
                        continue

                    diff = a_raw[both_valid] - b_raw[both_valid]
                    c_sub = c_raw[both_valid]
                    denom = c_sub.abs().clip(lower=1e-9)
                    rel_err = (c_sub - diff).abs() / denom

                    # Relationship confirmed: avg relative error < 1% and
                    # 95%+ of rows agree within 5%.
                    if rel_err.mean() < 0.01 and (rel_err < 0.05).mean() > 0.95:
                        a_clean = pd.to_numeric(df_clean[col_a], errors="coerce")
                        b_clean = pd.to_numeric(df_clean[col_b], errors="coerce")
                        recomputed_vals = a_clean - b_clean
                        n_updated = int(recomputed_vals.notna().sum())
                        df_clean[col_c] = recomputed_vals
                        recomputed.add(col_c)
                        self._log_fix(
                            {"type": "derived_column_recomputation", "column": col_c},
                            "auto_fixed",
                            f"Recomputed '{col_c}' = '{col_a}' − '{col_b}' "
                            f"after outlier capping to restore arithmetic "
                            f"consistency ({n_updated} rows updated)",
                            n_updated,
                        )
                        self.log(
                            "act",
                            f"Recomputed derived column '{col_c}' = '{col_a}' − '{col_b}'",
                        )
                        break
                if col_c in recomputed:
                    break

    def _run_gap_detection(self, df) -> list:
        """LLM gap detection on df_cleaned — finds issues that remain after
        all deterministic fixes. Returns a list of gap issues ready for
        CodeValidatorAgent.
        """
        # Per-column map of what was already fixed — explicit so LLM won't re-detect
        fixed_per_col: dict = {}
        for f in self.state.fix_log:
            if f["action"] == "auto_fixed":
                col = f["column"]
                fixed_per_col.setdefault(col, []).append(f"{f['issue_type']}: {f['description']}")

        # Already-handled (type, column) pairs — used for post-filter
        handled_pairs = {(f["issue_type"], f["column"]) for f in self.state.fix_log}

        col_to_issues: dict = {}
        for issue in self.state.prioritized_issues:
            col = issue.get("column", "")
            col_to_issues.setdefault(col, []).append(issue)

        sections = []
        for col in df.columns:
            nev = non_empty_values(df[col])
            if len(nev) == 0:
                continue
            sample = list(nev.sample(min(50, len(nev)), random_state=42).astype(str))
            dtype = str(df[col].dtype)
            already_fixed = fixed_per_col.get(col, [])
            sections.append(
                f"Column: '{col}' (dtype: {dtype})\n"
                f"Sample (current cleaned values): {sample}\n"
                f"Already fixed for this column: "
                f"{already_fixed if already_fixed else ['nothing']}"
            )

        if not sections:
            return []

        allowed_types_text = "\n".join(
            f"  {t}: {ISSUE_TYPES[t]}" for t in sorted(GAP_DETECTION_ISSUE_TYPES)
        )

        user = (
            f"Dataset domain: "
            f"{self.state.dataset_fingerprint.get('domain', 'unknown')}\n\n"
            + "\n\n".join(sections)
            + "\n\nYou are looking for data quality issues that REMAIN in the "
            "current cleaned values AFTER all automated fixes have been applied. "
            "The samples above show the CURRENT state of the data.\n\n"
            "Rules:\n"
            "- Only report issues clearly visible in the current sample values\n"
            "- Do NOT re-report issues listed in 'Already fixed for this column'\n"
            "- Do NOT flag missing values, sparse columns, duplicates, or naming issues\n"
            "- Each issue must be fixable with a simple pandas transformation\n"
            "- Use .astype(str) before any .str operations on non-object columns\n"
            "- If nothing new remains, return an empty list\n\n"
            f"Allowed issue types (use ONLY these):\n{allowed_types_text}\n\n"
            'Return JSON: {"gap_issues": [{"column": "...", "type": "...", '
            '"detail": "...", "severity": "high|medium|low", '
            '"filter": "pandas boolean expression selecting affected rows"}]}'
        )

        try:
            result = self.call_llm_json(user, max_tokens=2048, required_keys=["gap_issues"])
            gap_issues = result.get("gap_issues", [])
            valid = []
            for issue in gap_issues:
                col = issue.get("column", "")
                itype = issue.get("type", "")
                if not col or not itype:
                    continue
                if col not in df.columns:
                    continue
                if itype not in GAP_DETECTION_ISSUE_TYPES:
                    self.log("act", f"Gap issue rejected — type '{itype}' not in vocabulary")
                    continue
                if (itype, col) in handled_pairs:
                    self.log("act", f"Gap issue rejected — '{itype}' on '{col}' already handled")
                    continue
                if issue.get("severity") not in ("high", "medium", "low"):
                    continue
                valid.append({**issue, "source": "synthesis_gap_detection"})
                self.log(
                    "act", f"Post-remediation gap: '{col}' [{itype}] — {issue.get('detail', '')}"
                )
            self.log(
                "act", f"Post-remediation gap detection complete — {len(valid)} issue(s) found"
            )
            if valid:
                self.state.prioritized_issues.sort(
                    key=lambda x: SEVERITY_RANK.get(x.get("severity", "low"), 2)
                )
            return valid
        except Exception as e:
            self.log("error", f"Post-remediation gap detection failed: {e}")
            return []

    def _fix_missing_values(self, df, issue, fp):
        col = issue["column"]
        if col not in df.columns:
            return
        is_missing = missing_mask(df[col])
        rows_affected = int(is_missing.sum())
        if rows_affected == 0:
            return

        num_cols = set(fp.get("numerical_columns", []))
        date_cols = set(fp.get("date_columns", []))
        cat_cols = set(fp.get("categorical_columns", []))
        severity = issue.get("severity", "low")

        # Guard: never auto-impute binary flag columns (≤ 2 distinct valid
        # values such as 0/1 or True/False).  Imputing a flag changes the
        # event rate and introduces false signal.
        valid_vals = df.loc[~is_missing, col].dropna()
        if valid_vals.astype(str).str.strip().nunique() <= 2:
            self._log_fix(
                issue,
                "flagged_for_review",
                f"Binary flag column with {rows_affected} missing values "
                f"— auto-imputation suppressed to preserve flag distribution; "
                f"requires domain review",
                rows_affected,
            )
            return

        if col in num_cols:
            # Guard: median imputation on medium/high missingness biases
            # summary statistics; flag instead of auto-fill.
            if severity in ("high", "medium"):
                self._log_fix(
                    issue,
                    "flagged_for_review",
                    f"Numerical column with {rows_affected} missing values "
                    f"(severity={severity}): median imputation suppressed to "
                    f"prevent statistical bias — requires domain review",
                    rows_affected,
                )
                return
            success, detail = fill_missing_numerical(df, col, is_missing)
            action = "auto_fixed" if success else "flagged_for_review"
            self._log_fix(issue, action, detail, rows_affected)
        elif col in date_cols:
            self._log_fix(
                issue,
                "flagged_for_review",
                f"Date column with {rows_affected} missing values "
                f"-- requires domain knowledge to impute",
                rows_affected,
            )
        elif col in cat_cols:
            success, detail = fill_missing_categorical(df, col, is_missing, issue["severity"])
            action = "auto_fixed" if success else "flagged_for_review"
            self._log_fix(issue, action, detail, rows_affected)
        else:
            strategy = self._ask_llm_strategy(col, issue, fp)
            if strategy == "median":
                success, detail = fill_missing_numerical(df, col, is_missing)
                action = "auto_fixed" if success else "flagged_for_review"
                self._log_fix(issue, action, detail, rows_affected)
            elif strategy == "mode":
                success, detail = fill_missing_categorical(df, col, is_missing, issue["severity"])
                action = "auto_fixed" if success else "flagged_for_review"
                self._log_fix(issue, action, detail, rows_affected)
            else:
                self._log_fix(
                    issue,
                    "flagged_for_review",
                    f"Unclassified column with {rows_affected} missing values "
                    f"-- flagged for human review",
                    rows_affected,
                )

    def _ask_llm_strategy(self, col: str, issue: dict, fp: dict) -> str:
        domain = fp.get("domain", "unknown")
        user = (
            f"Column '{col}' has {issue['detail']}. "
            f"The dataset domain is '{domain}'. "
            f"Should this column be: (a) filled with median, "
            f"(b) filled with mode, or (c) left as-is for human review? "
            f'Respond ONLY with JSON: {{"strategy": "median"|"mode"|"flag", "reason": "..."}}'
        )
        try:
            result = self.call_llm_json(user, max_tokens=512, required_keys=["strategy"])
            strategy = result.get("strategy", "flag")
            reason = result.get("reason", "")
            self.log("act", f"LLM strategy for '{col}': {strategy} -- {reason}")
            return strategy if strategy in ("median", "mode", "flag") else "flag"
        except Exception as e:
            self.log("error", f"LLM remediation strategy failed for '{col}': {e}")
            return "flag"

    def _flag_issue(self, issue):
        descriptions = {
            "sparse_column": "Recommended for removal -- requires domain review",
            "duplicate_columns": "Columns may contain redundant data -- review for removal",
            "duplicate_key": "Rows share key values but differ elsewhere -- manual review needed",
            "date_order": "Cannot auto-fix date ordering without domain knowledge",
            "rare_categories": "Suggest grouping into 'Other' -- requires domain approval",
            "conditional_completeness": "Related column has gaps -- requires domain knowledge",
            "cross_column_mismatch": "Column value disagreement -- requires domain knowledge to resolve",
            "domain_negative_values": "Negative values in non-negative column -- requires manual review",
            "currency_symbol_in_numeric": "Currency symbols in numeric column -- requires locale-aware parsing",
            "comma_decimal_format": "Italian locale decimal format detected -- requires explicit conversion",
            "nd_placeholder_in_numeric": "N.D. placeholders in numeric column -- should be proper NULLs",
            "format_pattern_violation": "Values violating format pattern but no pattern stored -- flagged for review",
            "ambiguous_year_format": "2-digit year values -- century expanded automatically from dominant year in column",
            "invalid_year_value": "Year values outside [1900-2099] -- requires domain review before correction",
            "year_format_inconsistency": "Dirty year strings -- cleaned automatically (trailing non-digit noise stripped)",
        }
        desc = descriptions.get(issue["type"], "Flagged for human review")
        self._log_fix(issue, "flagged_for_review", desc, 0)

    def _log_fix(self, issue, action, description, rows_affected, **meta):
        entry = {
            "issue_type": issue["type"],
            "column": issue.get("column", ""),
            "action": action,
            "description": description,
            "rows_affected": rows_affected,
        }
        if meta:
            entry["metadata"] = meta
        self.state.fix_log.append(entry)
        self.log("act", f"[{action}] {issue.get('column', '')}: {description}")

    def observe(self):
        df_raw = self.state.df_raw
        df_clean = self.state.df_cleaned
        rows_removed = len(df_raw) - len(df_clean)
        cols_renamed = sum(
            1
            for f in self.state.fix_log
            if f["issue_type"] == "naming_convention" and f["action"] == "auto_fixed"
        )
        auto_fixed = sum(
            1 for f in self.state.fix_log if f["action"] in ("auto_fixed", "auto_fixed_by_llm")
        )
        flagged = sum(1 for f in self.state.fix_log if f["action"] == "flagged_for_review")
        self.log(
            "observe",
            f"Remediation complete: {auto_fixed} auto-fixed, "
            f"{flagged} flagged for review. "
            f"Rows removed: {rows_removed}, "
            f"columns renamed: {cols_renamed}. "
            f"df_cleaned shape: {df_clean.shape}",
        )

    def reply(self):
        fix_summary = (
            "\n".join(
                f"- [{f['action']}] {f['column']}: {f['description']}" for f in self.state.fix_log
            )
            or "No fixes applied."
        )
        auto_fixed = sum(
            1 for f in self.state.fix_log if f["action"] in ("auto_fixed", "auto_fixed_by_llm")
        )
        flagged = sum(1 for f in self.state.fix_log if f["action"] == "flagged_for_review")

        user = (
            f"Task: {self.prompt}\n\n"
            f"Fix actions:\n{fix_summary}\n\n"
            f"Write a concise summary (3-5 sentences) of what was remediated "
            f"and what was flagged for human review."
        )
        try:
            narrative = self.call_llm(user).strip()
        except Exception as e:
            self.log("error", str(e))
            narrative = (
                f"{auto_fixed} issues auto-remediated, {flagged} issues flagged for human review."
            )
        self.state.remediation_plan = self.state.fix_log
        self.log("reply", narrative)
