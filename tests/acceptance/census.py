"""Ground truth for the client datasets: enumerates the defects in the raw CSVs using rules
written independently of the pipeline's own detectors, so a run can be graded against an outside
reading of the file rather than against itself. Reads only the CSVs, so it needs no network and no
key, and writes checks/expected_defects.json for the other two checks to read.

    python checks/census.py Datasets-Reply-20260313/project_data_quality
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PLACEHOLDERS = {"", "n/a", "na", "n.a.", "-", "--", "null", "none", "nan", "?", "unknown",
                "sconosciuto", "non disponibile", "nd", "n.d.", "0000-00-00", "#n/a"}


def naming_violations(columns: list[str]) -> dict:
    out = {}
    for c in columns:
        flags = []
        if re.match(r"^\d", c):
            flags.append("leading_digit")
        if " " in c:
            flags.append("embedded_space")
        if re.search(r"[^0-9a-zA-Z_ ]", c):
            flags.append("special_char")
        if c != c.lower():
            flags.append("not_snake_lower")
        if flags:
            out[c] = flags
    return out


def norm_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().replace({"nan": ""})


def duplicate_columns(df: pd.DataFrame) -> list[dict]:
    cols = list(df.columns)
    pairs = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = norm_series(df[cols[i]]), norm_series(df[cols[j]])
            agree = float((a == b).mean())
            num_agree = None
            na = pd.to_numeric(df[cols[i]], errors="coerce")
            nb = pd.to_numeric(df[cols[j]], errors="coerce")
            both = na.notna() & nb.notna()
            if both.any():
                num_agree = float(np.isclose(na[both], nb[both]).mean())
            best = max([x for x in (agree, num_agree) if x is not None])
            if best >= 0.90:
                pairs.append({"left": cols[i], "right": cols[j],
                              "string_agreement": round(agree, 4),
                              "numeric_agreement": round(num_agree, 4) if num_agree is not None else None,
                              "exact": best >= 0.9999})
    return pairs


def placeholder_census(df: pd.DataFrame) -> dict:
    out = {}
    n = len(df)
    for c in df.columns:
        s = df[c]
        nulls = int(s.isna().sum())
        low = s.astype(str).str.strip().str.lower()
        disguised = {}
        present = set(low[s.notna()].unique()) & PLACEHOLDERS
        for tok in sorted(present):
            disguised[tok] = int((low == tok).sum())
        out[c] = {"nulls": nulls, "null_rate": round(nulls / n, 4),
                  "disguised": disguised,
                  "fully_empty": nulls == n,
                  "sparse": (nulls / n) > 0.9,
                  "n_unique": int(s.nunique(dropna=True))}
    return out


def numeric_findings(df: pd.DataFrame) -> dict:
    out = {}
    for c in df.columns:
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() < 10 or s.nunique(dropna=True) <= 20:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = int(((s < lo) | (s > hi)).sum())
        text = s.dropna().astype(str)
        decimals = text.str.split(".").str[-1].str.len().where(text.str.contains(r"\."), 0)
        noisy = int((decimals > 4).sum())
        out[c] = {"outliers_iqr": outliers,
                  "outlier_rate": round(outliers / int(s.notna().sum()), 4),
                  "min": float(s.min()), "max": float(s.max()),
                  "negatives": int((s < 0).sum()),
                  "float_noise_values": noisy}
    return out


def rare_categoricals(df: pd.DataFrame) -> dict:
    out = {}
    for c in df.columns:
        s = df[c].dropna()
        if s.empty:
            continue
        nu = s.nunique()
        if nu <= 1 or nu > 60 or nu / max(len(s), 1) > 0.5:
            continue
        counts = s.value_counts()
        rare = counts[counts < max(3, 0.01 * len(s))]
        if len(rare):
            out[c] = {"n_categories": int(nu), "n_rare": int(len(rare)),
                      "rare": {str(k): int(v) for k, v in list(rare.items())[:20]}}
    return out


def duplicate_rows(df: pd.DataFrame) -> dict:
    no_id = df.drop(columns=[c for c in df.columns if c == "_id"], errors="ignore")
    return {"exact_full_row": int(df.duplicated().sum()),
            "exact_ignoring_id": int(no_id.duplicated().sum()),
            "duplicate_id_values": int(df["_id"].duplicated().sum()) if "_id" in df.columns else None}


def cross_column(df: pd.DataFrame, name: str) -> dict:
    out = {}
    if name.startswith("attivazioni"):
        if {"RATA", "mese", "anno"} <= set(df.columns):
            anno = pd.to_numeric(df["anno"], errors="coerce").astype("Int64")
            mese = pd.to_numeric(df["mese"], errors="coerce").astype("Int64")
            rata = pd.to_numeric(df["RATA"], errors="coerce").astype("Int64")
            derived = anno.astype(str) + mese.astype(str).str.zfill(2)
            both = rata.notna() & mese.notna() & anno.notna()
            out["RATA_vs_anno_mese"] = {
                "checked": int(both.sum()),
                "mismatches": int((derived[both] != rata[both].astype(str)).sum()),
                "unparseable_anno": int(df["anno"].notna().sum() - anno.notna().sum()),
                "unparseable_mese": int(df["mese"].notna().sum() - mese.notna().sum()),
                "unparseable_RATA": int(df["RATA"].notna().sum() - rata.notna().sum())}
        for c in ("attivazioni", "cessazioni"):
            if c in df.columns:
                out[f"{c}_negative"] = int((pd.to_numeric(df[c], errors="coerce") < 0).sum())
    if name.startswith("spesa"):
        if {"cod_tipoimposta", "tipo_imposta"} <= set(df.columns):
            g = df.groupby("cod_tipoimposta")["tipo_imposta"].nunique(dropna=True)
            out["cod_tipoimposta_to_tipo_imposta"] = {
                "codes": int(len(g)), "codes_with_multiple_labels": int((g > 1).sum())}
        if {"cod_imposta", "imposta"} <= set(df.columns):
            g = df.groupby("cod_imposta")["imposta"].nunique(dropna=True)
            out["cod_imposta_to_imposta"] = {
                "codes": int(len(g)), "codes_with_multiple_labels": int((g > 1).sum())}
        if "spesa" in df.columns:
            out["spesa_negative"] = int((pd.to_numeric(df["spesa"], errors="coerce") < 0).sum())
    return out


def dtype_mismatch(df: pd.DataFrame) -> dict:
    out = {}
    for c in df.columns:
        s = df[c].dropna()
        if s.empty:
            continue
        stored = str(df[c].dtype)
        num = pd.to_numeric(s, errors="coerce")
        rate = float(num.notna().mean())
        if stored == "object" and 0.5 < rate < 1.0:
            offenders = s[num.isna()]
            out[c] = {"stored": stored, "numeric_parse_rate": round(rate, 4),
                      "verdict": "numeric column with malformed values",
                      "n_malformed": int(len(offenders)),
                      "malformed_examples": [str(v) for v in offenders.unique()[:15]]}
        elif stored == "object" and rate >= 1.0:
            out[c] = {"stored": stored, "numeric_parse_rate": 1.0,
                      "verdict": "object column holding only numbers"}
        elif stored.startswith("float") and num.notna().any() and bool((num.dropna() % 1 == 0).all()):
            out[c] = {"stored": stored, "verdict": "float column holding only integers"}
    return out


def format_consistency(df: pd.DataFrame) -> dict:
    """Intra-column format drift: values in a text column that do not share the dominant shape."""
    out = {}
    for c in df.columns:
        s = df[c].dropna().astype(str)
        if s.empty or s.nunique() <= 1:
            continue
        shape = (s.str.replace(r"\d", "9", regex=True)
                  .str.replace(r"[A-Za-z]", "a", regex=True))
        counts = shape.value_counts()
        if len(counts) <= 1:
            continue
        dominant = counts.index[0]
        share = float(counts.iloc[0] / len(s))
        minority = counts.iloc[1:]
        if 0.5 <= share < 1.0 and minority.sum() < 0.2 * len(s):
            examples = {}
            for pattern in minority.index[:5]:
                examples[pattern] = [str(v) for v in s[shape == pattern].unique()[:3]]
            out[c] = {"dominant_shape": dominant, "dominant_share": round(share, 4),
                      "n_offending": int(minority.sum()), "offending_shapes": examples}
    return out


def census(path: Path) -> dict:
    df = pd.read_csv(path)
    return {
        "dataset": path.stem,
        "path": str(path),
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "columns": list(df.columns),
        "pandas_dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "naming_violations": naming_violations(list(df.columns)),
        "duplicate_column_pairs": duplicate_columns(df),
        "completeness": placeholder_census(df),
        "dtype_mismatch": dtype_mismatch(df),
        "format_consistency": format_consistency(df),
        "numeric": numeric_findings(df),
        "rare_categoricals": rare_categoricals(df),
        "duplicate_rows": duplicate_rows(df),
        "cross_column": cross_column(df, path.stem),
    }


def summarise(name: str, c: dict) -> None:
    print(f"=== {name}  {c['shape']['rows']} x {c['shape']['columns']}")
    print(f"  naming violations      : {len(c['naming_violations'])} -> {list(c['naming_violations'])}")
    print(f"  duplicate column pairs : {len(c['duplicate_column_pairs'])}")
    for p in c["duplicate_column_pairs"]:
        print(f"      {p['left']!r} ~ {p['right']!r} str={p['string_agreement']} "
              f"num={p['numeric_agreement']} exact={p['exact']}")
    comp = c["completeness"]
    print(f"  fully empty columns    : {[k for k, v in comp.items() if v['fully_empty']]}")
    print(f"  sparse (>90pc null)    : {[k for k, v in comp.items() if v['sparse'] and not v['fully_empty']]}")
    print(f"  disguised placeholders : { {k: v['disguised'] for k, v in comp.items() if v['disguised']} }")
    print(f"  partial nulls          : { {k: v['nulls'] for k, v in comp.items() if 0 < v['nulls'] < c['shape']['rows']} }")
    print("  dtype mismatches       :")
    for col, v in c["dtype_mismatch"].items():
        print(f"      {col:22s} {v}")
    print("  format drift           :")
    for col, v in c["format_consistency"].items():
        print(f"      {col:22s} share={v['dominant_share']} offending={v['n_offending']} {v['offending_shapes']}")
    print(f"  duplicate rows         : {c['duplicate_rows']}")
    print(f"  numeric outliers       : { {k: v['outliers_iqr'] for k, v in c['numeric'].items()} }")
    print(f"  float noise            : { {k: v['float_noise_values'] for k, v in c['numeric'].items() if v['float_noise_values']} }")
    print(f"  negatives              : { {k: v['negatives'] for k, v in c['numeric'].items() if v['negatives']} }")
    print(f"  rare categoricals      : { {k: v['n_rare'] for k, v in c['rare_categoricals'].items()} }")
    print(f"  cross-column           : {json.dumps(c['cross_column'], ensure_ascii=False)}")
    print()


DEFAULT_SOURCES = Path(__file__).resolve().parent.parent / "Datasets-Reply-20260313" / "project_data_quality"
EXPECTED = Path(__file__).resolve().parent / "expected_defects.json"


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCES
    result = {p.stem: census(p) for p in sorted(root.glob("*.csv"))}
    EXPECTED.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    for dataset_name, findings in result.items():
        summarise(dataset_name, findings)
