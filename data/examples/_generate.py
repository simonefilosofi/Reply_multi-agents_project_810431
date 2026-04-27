"""Reproducible synthetic-dataset generator for the NoiPA pipeline test suite.

Defines four DataFrame builders consumed by ``tests/conftest.py`` and writes
matching CSV files under ``data/examples/`` when invoked as a script. Every
random draw is seeded so the resulting CSVs are byte-stable across runs.

Builders:
    - ``build_clean_pa_df()``: minimal canonical NoiPA-style payroll slice
      (rata, ente, descrizione, tipo_imposta, imposta, spesa); ~120 rows.
    - ``build_dirty_pa_df()``: same six-column schema, ~500 rows, injected
      with placeholders, full duplicates, mixed types, currency symbols,
      Italian comma-decimals, period-format variations, special month codes,
      two-digit years, mixed case and domain-negative values.
    - ``build_wide_dirty_df()``: 30-column dataset that exercises sparse
      columns, value-duplicate columns, semantic duplicate columns,
      conditional completeness (column B missing iff column A takes a given
      value), and lookup imputability (col_source -> col_target mapping).
    - ``build_large_synthetic_df()``: 5000-row scale-up of the dirty schema
      for performance smoke tests.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
DATA_DIR = Path(__file__).resolve().parent

ENTI = [
    "Ministero dell'Economia",
    "Ministero della Salute",
    "Comune di Roma",
    "Comune di Milano",
    "Regione Lazio",
    "Agenzia delle Entrate",
    "INPS",
    "INAIL",
]

DESCRIZIONI = [
    "Stipendio base",
    "Indennita di funzione",
    "Straordinario",
    "Trattenuta sindacale",
    "Buoni pasto",
    "Rimborso spese",
    "Premio produttivita",
    "Anticipo TFR",
]

TIPI_IMPOSTA = ["IRPEF", "IRES", "IRAP", "IVA", "INPS", "INAIL", "ADD_REG", "ADD_COM"]


def _rng() -> np.random.Generator:
    return np.random.default_rng(SEED)


def build_clean_pa_df(n_rows: int = 120) -> pd.DataFrame:
    """Return a clean NoiPA-style dataframe that scores high on every dimension."""
    rng = _rng()
    months = rng.integers(1, 13, size=n_rows)
    years = rng.integers(2022, 2026, size=n_rows)
    rata = [f"{y}{m:02d}" for y, m in zip(years, months, strict=True)]
    ente = rng.choice(ENTI, size=n_rows)
    descrizione = rng.choice(DESCRIZIONI, size=n_rows)
    tipo_imposta = rng.choice(TIPI_IMPOSTA, size=n_rows)
    imposta = np.round(rng.uniform(50.0, 1500.0, size=n_rows), 2)
    spesa = np.round(imposta * rng.uniform(2.0, 6.0, size=n_rows), 2)
    return pd.DataFrame(
        {
            "rata": rata,
            "ente": ente,
            "descrizione": descrizione,
            "tipo_imposta": tipo_imposta,
            "imposta": imposta,
            "spesa": spesa,
        }
    )


def _inject_placeholders(values: list[str], rng: np.random.Generator, rate: float) -> list[str]:
    placeholders = ["N.D.", "n.a.", "N/A", "sconosciuto", "", "  ", "non disponibile"]
    out = list(values)
    n_inject = int(len(out) * rate)
    idx = rng.choice(len(out), size=n_inject, replace=False)
    for i in idx:
        out[i] = str(rng.choice(placeholders))
    return out


def _inject_period_variations(rata: list[str], rng: np.random.Generator) -> list[str]:
    out = list(rata)
    n = len(out)
    n_dash = int(n * 0.10)
    n_mon = int(n * 0.05)
    n_slash = int(n * 0.05)
    n_text = int(n * 0.03)
    n_special = int(n * 0.04)
    n_twodigit = int(n * 0.05)
    indices = rng.permutation(n)
    cursor = 0

    def take(k: int) -> list[int]:
        nonlocal cursor
        sel: list[int] = list(indices[cursor : cursor + k].tolist())
        cursor += k
        return sel

    abbr = ["jan", "feb", "mar", "apr", "may", "jun", "gen", "feb", "mag", "giu", "lug", "ago"]
    for i in take(n_dash):
        y, m = out[i][:4], out[i][4:6]
        out[i] = f"{y}-{m}"
    for i in take(n_mon):
        y = out[i][:4]
        out[i] = f"{rng.choice(abbr)}-{y}"
    for i in take(n_slash):
        y, m = out[i][:4], out[i][4:6]
        out[i] = f"{m}/{y}"
    for i in take(n_text):
        y = out[i][:4]
        out[i] = f"Rata {y}"
    for i in take(n_special):
        y = out[i][:4]
        bad_month = rng.choice(["00", "13", "99"])
        out[i] = f"{y}{bad_month}"
    for i in take(n_twodigit):
        m = out[i][4:6]
        yy = rng.choice(["23", "24", "25"])
        out[i] = f"{m}/{yy}"
    return out


def _inject_currency_and_commas(values: np.ndarray, rng: np.random.Generator) -> list[str]:
    out: list[str] = []
    for v in values:
        roll = rng.random()
        if roll < 0.10:
            thousands = int(v) // 1000
            rest = round(v * 100) % 100000
            if thousands:
                base = f"{thousands}.{rest // 100:03d},{rest % 100:02d}"
            else:
                base = f"{int(v)},{round(v * 100) % 100:02d}"
            out.append(f"\u20ac {base}")
        elif roll < 0.20:
            out.append(f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        elif roll < 0.23:
            out.append("N.D.")
        elif roll < 0.25:
            out.append(f"-{v:.2f}")
        else:
            out.append(f"{v:.2f}")
    return out


def build_dirty_pa_df(n_rows: int = 500) -> pd.DataFrame:
    """Return a 6-column dirty NoiPA dataframe seeded for reproducibility.

    Injection rates and patterns are tuned so every detector listed in
    ``state_demo.constants.ISSUE_TYPES`` has at least one positive case.
    """
    rng = _rng()
    base = build_clean_pa_df(n_rows=n_rows)

    rata = _inject_period_variations(base["rata"].tolist(), rng)
    ente = _inject_placeholders(base["ente"].tolist(), rng, rate=0.08)

    descrizione = base["descrizione"].astype(str).tolist()
    n_x_suffix = int(len(descrizione) * 0.04)
    for i in rng.choice(len(descrizione), size=n_x_suffix, replace=False):
        descrizione[i] = f"{descrizione[i]} x"

    tipo_imposta = base["tipo_imposta"].astype(str).tolist()
    for i in rng.choice(len(tipo_imposta), size=int(len(tipo_imposta) * 0.15), replace=False):
        choice = rng.integers(0, 3)
        if choice == 0:
            tipo_imposta[i] = tipo_imposta[i].lower()
        elif choice == 1:
            tipo_imposta[i] = tipo_imposta[i].title()
        else:
            tipo_imposta[i] = "n.c."
    rare_idx = rng.choice(len(tipo_imposta), size=2, replace=False)
    for i in rare_idx:
        tipo_imposta[i] = "ZZZ_RARE"

    imposta_raw = base["imposta"].to_numpy()
    imposta = _inject_currency_and_commas(imposta_raw, rng)

    spesa = base["spesa"].to_numpy().astype(float)
    n_outliers = max(3, int(len(spesa) * 0.01))
    for i in rng.choice(len(spesa), size=n_outliers, replace=False):
        spesa[i] = spesa[i] * rng.uniform(50.0, 200.0)
    spesa_str: list[object] = [round(v, 2) for v in spesa]
    n_null = int(len(spesa_str) * 0.05)
    for i in rng.choice(len(spesa_str), size=n_null, replace=False):
        spesa_str[i] = np.nan

    df = pd.DataFrame(
        {
            "rata": rata,
            "ente": ente,
            "descrizione": descrizione,
            "tipo_imposta": tipo_imposta,
            "imposta": imposta,
            "spesa": spesa_str,
        }
    )

    n_dups = 8
    dup_rows = df.iloc[rng.choice(len(df), size=n_dups, replace=False)].copy()
    return pd.concat([df, dup_rows], ignore_index=True)


def build_wide_dirty_df(n_rows: int = 200) -> pd.DataFrame:
    """Return a 30-column dataset that exercises sparse / duplicate / lookup patterns."""
    rng = _rng()
    data: dict[str, object] = {}

    for i in range(1, 6):
        data[f"feature_{i}"] = rng.integers(0, 100, size=n_rows)

    sparse_a = np.array(["x"] * n_rows, dtype=object)
    drop_idx = rng.choice(n_rows, size=int(n_rows * 0.95), replace=False)
    for i in drop_idx:
        sparse_a[i] = np.nan
    data["sparse_a"] = sparse_a

    sparse_b = np.full(n_rows, np.nan, dtype=object)
    keep_idx = rng.choice(n_rows, size=int(n_rows * 0.05), replace=False)
    for i in keep_idx:
        sparse_b[i] = f"v{i}"
    data["sparse_b"] = sparse_b

    region_codes = ["RM", "MI", "NA", "TO", "BA"]
    region = rng.choice(region_codes, size=n_rows)
    data["region_code"] = region
    data["regione_codice"] = region.copy()

    region_to_capital = {
        "RM": "Roma",
        "MI": "Milano",
        "NA": "Napoli",
        "TO": "Torino",
        "BA": "Bari",
    }
    capital = np.array([region_to_capital[r] for r in region], dtype=object)
    n_blank = int(n_rows * 0.30)
    for i in rng.choice(n_rows, size=n_blank, replace=False):
        capital[i] = np.nan
    data["capoluogo"] = capital

    parent = rng.choice(["A", "B", "C"], size=n_rows)
    child = np.where(
        parent == "A",
        rng.choice(["a1", "a2"], size=n_rows),
        rng.choice(["b1", "b2", "c1"], size=n_rows),
    )
    child = child.astype(object)
    for i, p in enumerate(parent):
        if p == "C" and rng.random() < 0.85:
            child[i] = np.nan
    data["parent_cat"] = parent
    data["child_cat"] = child

    for i in range(1, 14):
        data[f"flag_{i}"] = rng.integers(0, 2, size=n_rows)

    cf_values = [f"AAA{rng.integers(10_000_000, 99_999_999)}" for _ in range(n_rows)]
    data["codice_fiscale"] = cf_values
    data["cf_dip"] = list(cf_values)

    importo_lordo = np.round(rng.uniform(1000.0, 5000.0, size=n_rows), 2)
    data["importo_lordo"] = importo_lordo
    data["importo_netto"] = importo_lordo * 0.7

    return pd.DataFrame(data)


def build_large_synthetic_df(n_rows: int = 5000) -> pd.DataFrame:
    """Return a 5000-row scale-up of the dirty schema for performance smoke tests."""
    return build_dirty_pa_df(n_rows=n_rows)


def write_examples() -> None:
    """Write all example CSVs to ``data/examples/``."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    build_clean_pa_df().to_csv(DATA_DIR / "clean_noipa_sample.csv", index=False, encoding="utf-8")
    build_dirty_pa_df().to_csv(DATA_DIR / "dirty_noipa_sample.csv", index=False, encoding="utf-8")
    build_large_synthetic_df().to_csv(
        DATA_DIR / "large_synthetic.csv", index=False, encoding="utf-8"
    )


if __name__ == "__main__":
    write_examples()
