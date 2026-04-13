"""Layer 0 ingestion agent. Reads raw datasets in CSV, JSON, Excel, or Parquet
format and stores the result as a string-typed DataFrame in PipelineState."""

import csv
import json

import pandas as pd

from agents.base_agent import BaseAgent


class IngestionAgent(BaseAgent):
    name = "ingestion"

    def think(self):
        self.log("think", f"Loading dataset from {self.state.source_path}")

    def act(self):
        path = self.state.source_path
        ext = path.rsplit(".", 1)[-1].lower()
        self.state.source_format = ext

        if ext == "csv":
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                sample = f.read(8192)
            try:
                dialect = csv.Sniffer().sniff(sample)
                sep = dialect.delimiter
            except csv.Error:
                sep = ","
            self.state.df_raw = pd.read_csv(
                path, sep=sep, dtype=str,
                encoding="utf-8", on_bad_lines="warn",
            )
        elif ext == "json":
            with open(path, encoding="utf-8") as f:
                self.state.df_raw = pd.json_normalize(
                    json.load(f),
                ).astype(str)
        elif ext in ("xlsx", "xls"):
            self.state.df_raw = pd.read_excel(path, dtype=str)
        elif ext == "parquet":
            self.state.df_raw = pd.read_parquet(path).astype(str)
        else:
            raise ValueError(f"Unsupported format: {ext}")

        self.state.ingestion_meta = {
            "source_format": ext,
            "rows": len(self.state.df_raw),
            "columns": len(self.state.df_raw.columns),
            "column_names": list(self.state.df_raw.columns),
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
