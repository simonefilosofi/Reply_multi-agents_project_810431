"""Layer 0 ingestion agent. Reads raw datasets in CSV, JSON, Excel, or Parquet
format and stores the result as a string-typed DataFrame in PipelineState.
"""

import pandas as pd

from agents_demo.base_agent import BaseAgent
from state_demo.helpers import missing_mask
from tools import load_dataset


class IngestionAgent(BaseAgent):
    name = "ingestion"

    INSTRUCTION = (
        "You are a data ingestion specialist responsible for loading raw datasets "
        "into the pipeline. You handle CSV, JSON, Excel, and Parquet formats, "
        "detect delimiters automatically, and record source metadata. "
        "You report concisely on what was loaded and flag any structural anomalies."
    )

    def think(self) -> None:
        self.log("think", self.prompt)

    def act(self) -> None:
        path = self.state.source_path
        df, ext = load_dataset(path)
        self.state.source_format = ext
        self.state.df_raw = df

        n_rows = len(df)
        n_cols = len(df.columns)
        total_cells = n_rows * n_cols
        if total_cells:
            mask_df = pd.DataFrame({c: missing_mask(df[c]) for c in df.columns}, index=df.index)
            empty_cells = int(mask_df.values.sum())
            empty_cell_rate = empty_cells / total_cells
            wholly_empty_rows = int(mask_df.all(axis=1).sum())
            wholly_empty_cols = int(mask_df.all(axis=0).sum())
        else:
            empty_cell_rate = 0.0
            wholly_empty_rows = 0
            wholly_empty_cols = 0

        self.state.ingestion_meta = {
            "source_format": ext,
            "rows": n_rows,
            "columns": n_cols,
            "column_names": list(df.columns),
            "total_cells": total_cells,
            "empty_cell_rate": empty_cell_rate,
            "wholly_empty_rows": wholly_empty_rows,
            "wholly_empty_cols": wholly_empty_cols,
        }

    def observe(self) -> None:
        meta = self.state.ingestion_meta
        self.log(
            "observe",
            f"Loaded {meta['rows']} rows, {meta['columns']} columns, "
            f"{meta['empty_cell_rate']:.1%} empty cells, "
            f"{meta['wholly_empty_rows']} empty rows, "
            f"{meta['wholly_empty_cols']} empty columns",
        )

    def reply(self) -> None:
        meta = self.state.ingestion_meta
        self.log(
            "reply",
            f"Ingestion complete: {meta['rows']} rows, "
            f"{meta['columns']} columns, "
            f"format={self.state.source_format}",
        )
