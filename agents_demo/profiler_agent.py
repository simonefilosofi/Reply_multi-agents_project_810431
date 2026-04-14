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
        "suggested_key_columns, column_descriptions. "
        "domain must be a short descriptive phrase (e.g. "
        "'public sector HR - employee activations', "
        "'municipal financial expenditure', "
        "'healthcare patient records'). "
        "language must be one of: italian, english, mixed. "
        "likely_duplicate_pairs is a list of [col_a, col_b] pairs where columns "
        "appear to contain the same data. "
        "No explanation, no markdown, just JSON."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        df = self.state.df_raw
        stats_block = compute_column_stats(df)
        user = (
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
