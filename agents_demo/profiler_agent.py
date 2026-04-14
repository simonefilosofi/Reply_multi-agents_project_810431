"""Layer 0 profiling agent. Uses LLM-driven semantic classification with a
statistical fallback to generate a DatasetFingerprint for downstream agents."""

import pandas as pd

from agents_demo.base_agent import BaseAgent, SMART
from state.fingerprint_schema import DatasetFingerprint
from state_demo.helpers import non_empty_values


class ProfilerAgent(BaseAgent):
    name = "profiler"
    model = SMART

    def think(self):
        self.log("think",
                 "Classifying columns by semantic type using LLM "
                 "with statistical fallback")

    def act(self):
        df = self.state.df_raw

        col_stats = []
        for col in df.columns:
            non_empty = non_empty_values(df[col])
            col_stats.append(
                f"- {col!r}: {len(non_empty)}/{len(df)} non-empty, "
                f"{non_empty.nunique()} unique, "
                f"sample={list(non_empty.head(5))}"
            )
        stats_block = "\n".join(col_stats)

        system = (
            "You are a dataset analyst. Given column statistics, "
            "return ONLY a valid JSON object with these exact keys: "
            "domain, language, id_columns, numerical_columns, "
            "categorical_columns, date_columns, sparse_columns, "
            "likely_duplicate_pairs, suggested_key_columns, "
            "column_descriptions. "
            "domain must be a short descriptive phrase (e.g. "
            "'public sector HR - employee activations', "
            "'municipal financial expenditure', "
            "'healthcare patient records'). "
            "language must be one of: italian, english, mixed. "
            "likely_duplicate_pairs is a list of [col_a, col_b] pairs "
            "where the columns appear to contain the same data. "
            "No explanation, no markdown, just JSON."
        )
        user = (
            f"Dataset: {len(df)} rows, {len(df.columns)} columns.\n"
            f"Column statistics:\n{stats_block}"
        )

        try:
            fingerprint_data = self.call_llm_json(system, user)
            fingerprint_data["domain"] = (
                fingerprint_data.get("domain") or "generic"
            )
            fingerprint_data["language"] = (
                fingerprint_data.get("language") or "mixed"
            ).lower()
            fp = DatasetFingerprint(**fingerprint_data)
            self.state.dataset_fingerprint = fp.model_dump()
            self.log("act",
                     f"LLM fingerprint OK. Domain={fp.domain}, "
                     f"Language={fp.language}")
        except Exception as e:
            self.log("error", f"LLM fingerprint failed: {e}")
            self.state.dataset_fingerprint = self._statistical_fallback(df)

    def observe(self):
        fp = self.state.dataset_fingerprint
        self.log("observe",
                 f"Fingerprint: domain={fp.get('domain')}, "
                 f"{len(fp.get('numerical_columns', []))} numerical, "
                 f"{len(fp.get('categorical_columns', []))} categorical, "
                 f"{len(fp.get('date_columns', []))} date, "
                 f"{len(fp.get('sparse_columns', []))} sparse columns")

    def reply(self):
        fp = self.state.dataset_fingerprint
        self.log("reply",
                 f"Profiling complete. Domain: {fp.get('domain')}, "
                 f"Language: {fp.get('language')}")

    def _statistical_fallback(self, df: pd.DataFrame) -> dict:
        numerical, categorical, date_cols, id_cols, sparse = (
            [], [], [], [], []
        )

        for col in df.columns:
            non_empty = non_empty_values(df[col])
            if len(df) == 0:
                continue

            null_rate = 1 - len(non_empty) / len(df)
            if null_rate > 0.90:
                sparse.append(col)
                continue

            num_frac = (
                pd.to_numeric(non_empty, errors="coerce").notna().mean()
            )

            if num_frac > 0.80:
                numerical.append(col)
            else:
                date_detected = False
                sample = non_empty.astype(str).head(100)
                pure_int_frac = sample.str.match(r"^\d+$").mean()
                if pure_int_frac <= 0.80:
                    parsed_dayfirst = pd.to_datetime(
                        sample, errors="coerce", dayfirst=True,
                    )
                    parsed_default = pd.to_datetime(
                        sample, errors="coerce",
                    )
                    date_parse_rate = max(
                        parsed_dayfirst.notna().mean(),
                        parsed_default.notna().mean(),
                    )
                    if date_parse_rate > 0.50:
                        date_cols.append(col)
                        date_detected = True

                if not date_detected:
                    if (non_empty.nunique()
                            / max(len(non_empty), 1) < 0.05):
                        categorical.append(col)

            col_lower = col.lower().strip()
            col_tokens = set(col_lower.split("_"))
            id_indicators = {"codice", "matricola", "fiscal", "cf"}
            if (col_lower in ("_id", "id")
                    or col_lower.endswith("_id")
                    or bool(col_tokens & id_indicators)):
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
