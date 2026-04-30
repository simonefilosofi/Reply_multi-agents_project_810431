"""Extracts column names, dtypes, and format patterns and serializes them to baseline.json."""
from __future__ import annotations

import json

import pandas as pd

from models import BaselineFile, ColumnSchema, DomainBaseline


def extract_column_schema(
    clustered: dict[str, list[pd.DataFrame]],
    output_path: str = "baseline.json",
) -> BaselineFile:
    domains: list[DomainBaseline] = []
    for domain, dfs in clustered.items():
        col_counts: dict[str, dict] = {}
        for df in dfs:
            for col in df.columns:
                dtype = str(df[col].dtype)
                col_counts.setdefault(col, {"dtype": dtype, "count": 0})
                col_counts[col]["count"] += 1
        columns = [
            ColumnSchema(column_name=col, dtype=info["dtype"])
            for col, info in col_counts.items()
        ]
        domains.append(DomainBaseline(domain=domain, columns=columns))

    baseline = BaselineFile(domains=domains)
    with open(output_path, "w") as f:
        f.write(baseline.model_dump_json(indent=2))
    return baseline
