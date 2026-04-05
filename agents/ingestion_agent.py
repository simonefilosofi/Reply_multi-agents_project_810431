import csv
import pandas as pd
from agents.base_agent import BaseAgent


class IngestionAgent(BaseAgent):
    name = "ingestion"

    def run(self):
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
                encoding="utf-8", on_bad_lines="warn"
            )

        elif ext == "json":
            self.state.df_raw = pd.json_normalize(
                pd.read_json(path, dtype=str).to_dict("records")
            )

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
        print(f"[Ingestion] Loaded {self.state.ingestion_meta['rows']} rows, "
              f"{self.state.ingestion_meta['columns']} columns.")
