"""Italian-locale registry for the NoiPA data-quality pipeline.

Single source of truth for the Italian-domain knowledge that the consistency
and constraint agents (and the deterministic remediation pass) need to share:
month-name lookups, the Italian-administrative placeholder set, the currency
symbol set, the Italian comma-decimal pattern, and the N.D. / N.A. tokens that
appear inside otherwise-numeric columns.

The tables here are consumed from Step 6 onward; this module is intentionally
free of any pipeline import so it can be loaded by tools, agents, and tests
without creating cycles.
"""

from __future__ import annotations

import re

MONTH_ABBR_IT_EN: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "gen": 1,
    "mag": 5,
    "giu": 6,
    "lug": 7,
    "ago": 8,
    "set": 9,
    "ott": 10,
    "dic": 12,
}

MONTH_FULL_IT_EN: dict[str, int] = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

IT_EN_MONTH_TRANSLATION: dict[str, str] = {
    "gen": "jan",
    "feb": "feb",
    "mar": "mar",
    "apr": "apr",
    "mag": "may",
    "giu": "jun",
    "lug": "jul",
    "ago": "aug",
    "set": "sep",
    "ott": "oct",
    "nov": "nov",
    "dic": "dec",
    "gennaio": "january",
    "febbraio": "february",
    "marzo": "march",
    "aprile": "april",
    "maggio": "may",
    "giugno": "june",
    "luglio": "july",
    "agosto": "august",
    "settembre": "september",
    "ottobre": "october",
    "novembre": "november",
    "dicembre": "december",
}

ITALIAN_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "sconosciuto",
        "non disponibile",
        "non applicabile",
        "da verificare",
        "da definire",
        "da inserire",
        "da completare",
        "in attesa",
        "non pervenuto",
        "non rilevato",
        "non classificato",
        "n.c.",
        "nc",
    }
)

CURRENCY_SYMBOLS: frozenset[str] = frozenset({"\u20ac", "$", "\u00a3", "\u00a5"})

IT_DECIMAL_PATTERN: re.Pattern[str] = re.compile(r"^\d{1,3}(\.\d{3})*(,\d+)?$")

ND_PATTERNS: frozenset[str] = frozenset(
    {
        "n.d.",
        "nd",
        "n/d",
        "n.a.",
        "na",
        "n/a",
        "#n/d",
        "#nd",
    }
)
