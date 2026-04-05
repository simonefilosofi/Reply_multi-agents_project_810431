import pandas as pd
from agents.base_agent import BaseAgent, SMART
from state.fingerprint_schema import DatasetFingerprint


class ProfilerAgent(BaseAgent):
    name = "profiler"
    model = SMART

    def run(self):
        df = self.state.df_raw

        # Build column statistics for the LLM prompt
        col_stats = []
        for col in df.columns:
            non_empty = df[col].dropna()
            non_empty = non_empty[non_empty.astype(str).str.strip() != ""]
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
            "likely_duplicate_pairs is a list of [col_a, col_b] pairs "
            "where the columns appear to contain the same data. "
            "No explanation, no markdown, just JSON."
        )
        user = (
            f"Dataset: {len(df)} rows, {len(df.columns)} columns.\n"
            f"Column statistics:\n{stats_block}"
        )

        try:
            raw = self.call_llm_json(system, user)
            fp = DatasetFingerprint(**raw)
            self.state.dataset_fingerprint = fp.model_dump()
            print(f"[Profiler] LLM fingerprint OK. "
                  f"Domain={fp.domain}, Language={fp.language}, "
                  f"Duplicate pairs={len(fp.likely_duplicate_pairs)}")
        except Exception as e:
            print(f"[Profiler] LLM failed ({e}), using statistical fallback.")
            self.state.dataset_fingerprint = self._statistical_fallback(df)

    def _statistical_fallback(self, df):
        numerical, categorical, date_cols, id_cols, sparse = [], [], [], [], []

        for col in df.columns:
            non_empty = df[col].dropna()
            non_empty = non_empty[non_empty.astype(str).str.strip() != ""]
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
            elif non_empty.nunique() / max(len(non_empty), 1) < 0.05:
                categorical.append(col)

            col_lower = col.lower().strip()
            if col_lower in ("_id", "id") or col_lower.endswith("_id"):
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
