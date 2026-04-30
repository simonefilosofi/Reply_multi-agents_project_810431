"""Layer 0 profiling agent. Uses LLM-driven semantic classification with a
statistical fallback to generate a DatasetFingerprint for downstream agents.
Step 8 adds a hallucination guard that re-validates LLM-inferred constraints
against the actual data and records every self-correction in
PipelineState.cross_agent_insights.
"""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from agents_demo.base_agent import SMART, BaseAgent
from state.fingerprint_schema import DatasetFingerprint
from state.helpers import missing_mask
from tools import compute_column_stats, statistical_fingerprint

_TYPED_COLUMN_FIELDS = (
    "id_columns",
    "numerical_columns",
    "categorical_columns",
    "date_columns",
    "sparse_columns",
    "suggested_key_columns",
)

_MUST_EQUAL_AGREEMENT_THRESHOLD = 0.80
_NUMERIC_COERCIBLE_THRESHOLD = 0.50
_FORMAT_PATTERN_MATCH_THRESHOLD = 0.50
_DATE_PARSE_THRESHOLD = 0.50


class ProfilerAgent(BaseAgent):
    name = "profiler"
    MODEL_TIER = SMART

    INSTRUCTION = (
        "You are a dataset profiling specialist. Given column statistics, "
        "classify each column by semantic type and return ONLY a valid JSON object "
        "with these exact keys: domain, language, id_columns, numerical_columns, "
        "categorical_columns, date_columns, sparse_columns, likely_duplicate_pairs, "
        "suggested_key_columns, column_descriptions, column_constraints. "
        "domain must be a short descriptive phrase (e.g. "
        "'public sector HR - employee activations', "
        "'municipal financial expenditure', "
        "'healthcare patient records'). "
        "language must be one of: italian, english, mixed. "
        "CRITICAL classification rules — read carefully: "
        "numerical_columns must contain ONLY true continuous quantities (monetary "
        "amounts, measurements, counts). Do NOT put codes, identifiers, or period "
        "keys in numerical_columns even if they look numeric. "
        "date_columns must include columns with standard parseable date strings "
        "(ISO dates, YYYYMMDD integers, datetime strings). "
        "Do NOT put YYYYMM period codes (like 202401, 202402) in date_columns — "
        "put them in categorical_columns instead, because they cannot be parsed "
        "by standard date parsers and would be destroyed if treated as dates. "
        "categorical_columns must include integer enum codes, type codes, and "
        "any column with low cardinality discrete values (e.g. cod_tipoimposta, "
        "cod_imposta, ente, area_geografica). "
        "Standalone month columns (named 'mese', 'month', or similar; values 1-12 "
        "with possible special codes -1, 0, 13, 99) must go in categorical_columns. "
        "Standalone year columns (named 'anno', 'year', or similar; values are "
        "4-digit years like 2021-2024) must also go in categorical_columns — do NOT "
        "put them in numerical_columns. "
        "id_columns must include any column that uniquely identifies a record "
        "or entity (_id, document ids, etc.). "
        "likely_duplicate_pairs is a list of [col_a, col_b] pairs where columns "
        "appear to contain the same data. "
        "column_constraints is a list of domain-rule objects you can infer from "
        "column names and sample values. Each object must have a 'column' key and "
        "a 'type' key. Supported types and their extra keys: "
        "(1) 'must_equal_column': {'other_column': str, 'description': str} — "
        "two columns that should hold identical values per row (e.g. denormalized "
        "copies of the same field); "
        "(2) 'no_negatives': {'description': str} — numeric column where negative "
        "values are domain-impossible (e.g. amounts, counts, prices); "
        "(3) 'format_pattern': {'pattern': str, 'description': str} — column "
        "values must match this Python regex (e.g. period codes YYYYMM: "
        "pattern='^\\\\d{6}\\\\.0$' or '^\\\\d{6}$'). "
        "Only emit constraints you are confident about from the column name and "
        "sample values. Omit column_constraints entirely if you have no confident "
        "constraints to report. "
        "No explanation, no markdown, just JSON."
    )

    def think(self) -> None:
        self.log("think", self.prompt)

    def act(self) -> None:
        df = self.state.df_raw
        stats_block = compute_column_stats(df)
        user = (
            f"Task: {self.prompt}\n\n"
            f"Dataset: {len(df)} rows, {len(df.columns)} columns.\n"
            f"Column statistics:\n{stats_block}"
        )
        try:
            fp: DatasetFingerprint = self.call_llm_json(user, schema=DatasetFingerprint)
            corrections_before = len(self.state.cross_agent_insights)
            fp = self._validate_constraints_against_data(fp, df)
            n_corrections = len(self.state.cross_agent_insights) - corrections_before
            self.state.dataset_fingerprint = fp.model_dump()
            self.log(
                "act",
                f"LLM fingerprint OK. Domain={fp.domain}, Language={fp.language}, "
                f"profiler self-corrections={n_corrections}",
            )
        except Exception as exc:
            self.log("error", f"LLM fingerprint failed: {exc}")
            self.state.dataset_fingerprint = statistical_fingerprint(df)

    def observe(self) -> None:
        fp = self.state.dataset_fingerprint
        self.log(
            "observe",
            f"Fingerprint: domain={fp.get('domain')}, "
            f"{len(fp.get('numerical_columns', []))} numerical, "
            f"{len(fp.get('categorical_columns', []))} categorical, "
            f"{len(fp.get('date_columns', []))} date, "
            f"{len(fp.get('sparse_columns', []))} sparse columns",
        )

    def reply(self) -> None:
        fp = self.state.dataset_fingerprint
        self.log(
            "reply",
            f"Profiling complete. Domain: {fp.get('domain')}, Language: {fp.get('language')}",
        )

    def _record_correction(self, subject: str, column: str, detail: str) -> None:
        self.state.cross_agent_insights.append(
            {
                "agent": self.name,
                "type": "profiler_self_correction",
                "subject": subject,
                "column": column,
                "detail": detail,
            }
        )

    def _validate_constraints_against_data(
        self, fp: DatasetFingerprint, df: pd.DataFrame
    ) -> DatasetFingerprint:
        cleaned = fp.model_dump()
        df_columns = set(df.columns)

        for column_field in _TYPED_COLUMN_FIELDS:
            kept: list[str] = []
            for col in cleaned[column_field]:
                if col in df_columns:
                    kept.append(col)
                else:
                    self._record_correction(
                        "unknown_column",
                        col,
                        f"Column listed in {column_field} but absent from the dataframe",
                    )
            cleaned[column_field] = kept

        retained_dates: list[str] = []
        for col in cleaned["date_columns"]:
            parse_rate = max(
                float(pd.to_datetime(df[col], errors="coerce", dayfirst=True).notna().mean()),
                float(pd.to_datetime(df[col], errors="coerce").notna().mean()),
            )
            if parse_rate < _DATE_PARSE_THRESHOLD:
                self._record_correction(
                    "date_demotion",
                    col,
                    f"Date parse rate {parse_rate:.1%} < {_DATE_PARSE_THRESHOLD:.0%} — "
                    "demoted to categorical",
                )
                if col not in cleaned["categorical_columns"]:
                    cleaned["categorical_columns"].append(col)
            else:
                retained_dates.append(col)
        cleaned["date_columns"] = retained_dates

        surviving_constraints: list[dict[str, Any]] = []
        for constraint in cleaned.get("column_constraints", []):
            ctype = constraint.get("type")
            col = constraint.get("column")
            if not col or col not in df_columns:
                self._record_correction(
                    "unknown_column",
                    str(col or ""),
                    f"column_constraint of type {ctype!r} targets unknown column",
                )
                continue

            if ctype == "must_equal_column":
                other = constraint.get("other_column")
                if not isinstance(other, str) or other not in df_columns:
                    self._record_correction(
                        "must_equal_column",
                        col,
                        f"other_column={other!r} is missing or absent from the dataframe",
                    )
                    continue
                clean_mask = ~missing_mask(df[col]) & ~missing_mask(df[other])
                if int(clean_mask.sum()) == 0:
                    self._record_correction(
                        "must_equal_column",
                        col,
                        f"no comparable clean rows against {other!r}",
                    )
                    continue
                left = df.loc[clean_mask, col].astype(str).str.strip()
                right = df.loc[clean_mask, other].astype(str).str.strip()
                agreement = float((left == right).mean())
                if agreement < _MUST_EQUAL_AGREEMENT_THRESHOLD:
                    self._record_correction(
                        "must_equal_column",
                        col,
                        f"agreement {agreement:.1%} < "
                        f"{_MUST_EQUAL_AGREEMENT_THRESHOLD:.0%} threshold "
                        f"against {other!r}",
                    )
                    continue
            elif ctype == "no_negatives":
                coercible = float(pd.to_numeric(df[col], errors="coerce").notna().mean())
                if coercible < _NUMERIC_COERCIBLE_THRESHOLD:
                    self._record_correction(
                        "no_negatives",
                        col,
                        f"numeric-coercion rate {coercible:.1%} < "
                        f"{_NUMERIC_COERCIBLE_THRESHOLD:.0%} threshold",
                    )
                    continue
            elif ctype == "format_pattern":
                pattern = constraint.get("pattern")
                if not isinstance(pattern, str):
                    self._record_correction(
                        "format_pattern",
                        col,
                        "missing or non-string 'pattern' field",
                    )
                    continue
                try:
                    regex = re.compile(pattern)
                except re.error as regex_err:
                    self._record_correction(
                        "format_pattern",
                        col,
                        f"invalid regex {pattern!r}: {regex_err}",
                    )
                    continue
                clean_values = df[col][~missing_mask(df[col])].astype(str)
                if len(clean_values) == 0:
                    self._record_correction(
                        "format_pattern",
                        col,
                        "no clean values to evaluate against pattern",
                    )
                    continue
                match_rate = float(clean_values.str.contains(regex, regex=True, na=False).mean())
                if match_rate < _FORMAT_PATTERN_MATCH_THRESHOLD:
                    self._record_correction(
                        "format_pattern",
                        col,
                        f"pattern {pattern!r} matched {match_rate:.1%} of clean values "
                        f"(< {_FORMAT_PATTERN_MATCH_THRESHOLD:.0%} threshold)",
                    )
                    continue

            surviving_constraints.append(constraint)
        cleaned["column_constraints"] = surviving_constraints

        return DatasetFingerprint.model_validate(cleaned)
