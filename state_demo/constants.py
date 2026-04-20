"""Shared constants used across multiple agents in the data quality pipeline."""

import re

PLACEHOLDERS = {
    "n/a", "na", "n.a.", "n.d.", "nd", "n/d", "null", "none", "-",
    "--", ".", "..", "...", "unknown", "missing", "tbd",
    "not available", "not applicable", "sconosciuto",
    "non disponibile", "non applicabile",
    "//", "///", "?", "??", "???", "#", "#n/d", "#nd", "#n/a",
}

DATE_PATTERNS = [
    ("DD/MM/YYYY", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")),
    ("DD-MM-YYYY", re.compile(r"^\d{2}-\d{2}-\d{4}$")),
    ("DD.MM.YYYY", re.compile(r"^\d{2}\.\d{2}\.\d{4}$")),
    ("YYYY-MM-DD", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("YYYYMMDD", re.compile(r"^\d{8}$")),
]

DATE_FORMAT_MAP = {
    "DD/MM/YYYY": "%d/%m/%Y",
    "DD-MM-YYYY": "%d-%m-%Y",
    "DD.MM.YYYY": "%d.%m.%Y",
    "YYYY-MM-DD": "%Y-%m-%d",
    "YYYYMMDD": "%Y%m%d",
}

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
