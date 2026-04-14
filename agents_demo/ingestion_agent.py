"""Layer 0 ingestion agent. Reads raw datasets in CSV, JSON, Excel, or Parquet
format and stores the result as a string-typed DataFrame in PipelineState."""

from agents_demo.base_agent import BaseAgent
from tools import load_dataset


class IngestionAgent(BaseAgent):
    name = "ingestion"

    INSTRUCTION = (
        "You are a data ingestion specialist responsible for loading raw datasets "
        "into the pipeline. You handle CSV, JSON, Excel, and Parquet formats, "
        "detect delimiters automatically, and record source metadata. "
        "You report concisely on what was loaded and flag any structural anomalies."
    )

    def think(self):
        self.log("think", self.prompt)

    def act(self):
        path = self.state.source_path
        df, ext = load_dataset(path)
        self.state.source_format = ext
        self.state.df_raw = df
        self.state.ingestion_meta = {
            "source_format": ext,
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns),
        }

    def observe(self):
        meta = self.state.ingestion_meta
        self.log("observe",
                 f"Loaded {meta['rows']} rows, {meta['columns']} columns")

    def reply(self):
        meta = self.state.ingestion_meta
        self.log("reply",
                 f"Ingestion complete: {meta['rows']} rows, "
                 f"{meta['columns']} columns, "
                 f"format={self.state.source_format}")
