"""Fetches and downloads datasets from the Italian PA open-data portal (dati.gov.it)."""
from __future__ import annotations

import pandas as pd


def scrape_pa_datasets(max_datasets: int = 20) -> list[pd.DataFrame]:
    # TODO: use requests + CKAN API at https://www.dati.gov.it/api/3/action/package_search
    # to list datasets, download CSVs, and return as DataFrames
    return []
