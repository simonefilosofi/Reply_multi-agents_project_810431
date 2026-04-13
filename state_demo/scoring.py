"""Unified reliability score computation shared by SynthesisAgent and ReportAgent."""

from itertools import combinations
from typing import Callable, Optional

import pandas as pd

from state.helpers import missing_mask


def compute_reliability_score(
    df: pd.DataFrame,
    state,
    resolve: Optional[Callable[[str], Optional[str]]] = None,
):
    fp = state.dataset_fingerprint
    total_rows = len(df)
    total_cols = len(df.columns)

    if total_rows == 0:
        return 100.0, {
            "schema_conformity": 1.0, "completeness": 1.0,
            "uniqueness": 1.0, "consistency": 1.0,
        }

    if resolve is None:
        def resolve(col):
            return col if col in df.columns else None

    type_issue_count = 0
    for col in fp.get("numerical_columns", []):
        r = resolve(col)
        if r is None:
            continue
        if pd.api.types.is_numeric_dtype(df[r]):
            continue
        numeric = pd.to_numeric(df[r], errors="coerce")
        coerced = int(numeric.isna().sum()) - int(df[r].isna().sum())
        if coerced > 0:
            type_issue_count += 1

    for col in fp.get("date_columns", []):
        r = resolve(col)
        if r is None:
            continue
        if pd.api.types.is_datetime64_any_dtype(df[r]):
            bad_frac = df[r].isna().mean()
        else:
            bad_frac = pd.to_datetime(
                df[r], errors="coerce", dayfirst=True,
            ).isna().mean()
        if bad_frac > 0.10:
            type_issue_count += 1

    naming_issue_count = 0
    for issue in state.schema_report.get("issues", []):
        if issue["type"] == "naming_convention":
            if issue["column"] in df.columns:
                naming_issue_count += 1

    schema_dim = max(0.0,
        (total_cols - type_issue_count - naming_issue_count)
        / max(total_cols, 1)
    )

    total_cells = total_rows * total_cols
    total_missing = sum(
        int(missing_mask(df[col]).sum()) for col in df.columns
    )
    completeness_dim = 1 - (total_missing / max(total_cells, 1))

    uniqueness_dim = 1 - (int(df.duplicated().sum()) / total_rows)

    violation_mask = pd.Series(False, index=df.index)
    date_cols_resolved = [
        r for col in fp.get("date_columns", [])
        if (r := resolve(col)) is not None
    ]
    for col_a, col_b in combinations(date_cols_resolved, 2):
        if pd.api.types.is_datetime64_any_dtype(df[col_a]):
            pa = df[col_a]
        else:
            pa = pd.to_datetime(
                df[col_a], errors="coerce", dayfirst=True,
            )
        if pd.api.types.is_datetime64_any_dtype(df[col_b]):
            pb = df[col_b]
        else:
            pb = pd.to_datetime(
                df[col_b], errors="coerce", dayfirst=True,
            )
        both_valid = pa.notna() & pb.notna()
        violation_mask |= (both_valid & (pa > pb))
    consistency_dim = 1 - (int(violation_mask.sum()) / total_rows)

    num_cols_resolved = [
        r for col in fp.get("numerical_columns", [])
        if (r := resolve(col)) is not None
    ]
    total_numeric_values = 0
    total_outliers = 0
    for col in num_cols_resolved:
        if pd.api.types.is_numeric_dtype(df[col]):
            numeric = df[col].dropna()
        else:
            numeric = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(numeric) < 2:
            continue
        total_numeric_values += len(numeric)
        mean, std = numeric.mean(), numeric.std()
        if std > 0:
            total_outliers += int(
                ((numeric - mean).abs() > 3 * std).sum()
            )

    schema_dim = max(0.0, min(1.0, schema_dim))
    completeness_dim = max(0.0, min(1.0, completeness_dim))
    uniqueness_dim = max(0.0, min(1.0, uniqueness_dim))
    consistency_dim = max(0.0, min(1.0, consistency_dim))

    dims = [
        ("schema_conformity", schema_dim, 20),
        ("completeness", completeness_dim, 25),
        ("uniqueness", uniqueness_dim, 20),
        ("consistency", consistency_dim, 20),
    ]
    if total_numeric_values > 0:
        anomaly_dim = max(0.0, min(1.0,
            1 - (total_outliers / total_numeric_values),
        ))
        dims.append(("anomaly_freedom", anomaly_dim, 15))

    total_weight = sum(w for _, _, w in dims)
    score = sum(v * w for _, v, w in dims) / total_weight * 100
    dim_values = {k: round(v, 4) for k, v, _ in dims}
    return round(score, 1), dim_values
