"""Layer 0 profiling agent. Uses LLM-driven semantic classification with a
statistical fallback to generate a DatasetFingerprint for downstream agents."""

from agents_demo.base_agent import BaseAgent, SMART
from state_demo.fingerprint_schema import DatasetFingerprint
from tools import compute_column_stats, statistical_fingerprint


class ProfilerAgent(BaseAgent):
    name = "profiler"
    model = SMART

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

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        stats_block = compute_column_stats(df)
        user = (
            f"Task: {self.prompt}\n\n"
            f"Dataset: {len(df)} rows, {len(df.columns)} columns.\n"
            f"Column statistics:\n{stats_block}"
        )
        try:
            data = self.call_llm_json(user)
            data["domain"] = data.get("domain") or "generic"
            data["language"] = (data.get("language") or "mixed").lower()
            fp = DatasetFingerprint(**data)
            self.state.dataset_fingerprint = fp.model_dump()
            self.log("act",
                     f"LLM fingerprint OK. Domain={fp.domain}, "
                     f"Language={fp.language}")
        except Exception as e:
            self.log("error", f"LLM fingerprint failed: {e}")
            self.state.dataset_fingerprint = statistical_fingerprint(df)

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
