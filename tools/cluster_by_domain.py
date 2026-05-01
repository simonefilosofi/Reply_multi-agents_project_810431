"""Groups a list of DataFrames by thematic domain using metadata or LLM classification."""
from __future__ import annotations

import pandas as pd


def cluster_by_domain(datasets: list[pd.DataFrame]) -> dict[str, list[pd.DataFrame]]:
    # TODO: use dataset metadata tags from the CKAN API response, falling back to LLM
    # classification against a fixed taxonomy of PA domains
    return {}
