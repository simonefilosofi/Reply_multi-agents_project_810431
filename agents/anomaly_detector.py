"""Detects numeric outliers (IQR method) and rare categorical values per column using pure pandas/numpy, then asks the LLM for a one-sentence explanatory comment per column. The method is chosen from what the column means rather than from its current dtype: identifiers and free-text columns are skipped, codes are never treated as magnitudes (a numeric column with few distinct values is a code, whatever its dtype says), and only genuinely categorical columns are scanned for rare values."""
from __future__ import annotations

import json

import pandas as pd
from pydantic import BaseModel

from models import AnomalyEntry, AnomalyReport
from tools.normalize_numeric_format import normalize_numeric_format
from state import PipelineState
from utils.llm import structured_model
from utils.prompts import load_prompt

_RARE_FREQ_THRESHOLD = 0.01  # below 1% of non-null rows
_RARE_ABS_THRESHOLD = 3      # or fewer than 3 absolute occurrences
_OUTLIER_CAP = 50            # max anomaly entries stored per column, both methods
_IDENTIFIER_UNIQUENESS = 0.9
_MAX_CATEGORY_VALUES = 30
_NUMERIC_READ_THRESHOLD = 0.9
_KEY_TOKENS = ("code", "identifier", "id ", " id", "key", "codice")


class _ColumnComment(BaseModel):
    column_name: str
    comment: str


class _AnomalyCommentResponse(BaseModel):
    column_comments: list[_ColumnComment]


def anomaly_detector_node(state: PipelineState) -> PipelineState:
    if state.dataset is None:
        return state

    df = state.dataset
    reports: list[AnomalyReport] = []

    meanings = {p.column_name: p.description for p in state.payload}
    for col in df.columns:
        series = df[col]
        clean = series.dropna()
        if len(clean) == 0:
            continue

        role = _column_role(series, meanings.get(col, ""))
        if role == "measure":
            report = _detect_numeric_outliers(series, col)
        elif role == "category":
            report = _detect_rare_categories(series, col)
        else:
            continue

        if report is not None and report.anomalies:
            reports.append(report)

    if reports:
        _add_llm_comments(reports)

    return state.model_copy(update={"anomaly_reports": reports})


def _column_role(series: pd.Series, meaning: str) -> str:
    populated = int(series.notna().sum())
    if not populated:
        return "skip"
    if series.nunique(dropna=True) / populated >= _IDENTIFIER_UNIQUENESS:
        return "identifier"

    if pd.api.types.is_datetime64_any_dtype(series):
        return "temporal"

    numeric = pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)
    described_as_key = any(token in meaning.lower() for token in _KEY_TOKENS)
    if not numeric and _reads_as_numeric(series):
        numeric, series = True, _as_numeric(series)
    if numeric:
        if described_as_key or series.nunique(dropna=True) <= _MAX_CATEGORY_VALUES:
            return "code"
        return "measure"
    if series.nunique(dropna=True) <= _MAX_CATEGORY_VALUES:
        return "category"
    return "free-text"


def _reads_as_numeric(series: pd.Series) -> bool:
    populated = int(series.notna().sum())
    if not populated:
        return False
    return _as_numeric(series).notna().sum() / populated >= _NUMERIC_READ_THRESHOLD


def _as_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(normalize_numeric_format(series), errors="coerce")


def _detect_numeric_outliers(series: pd.Series, col_name: str) -> AnomalyReport | None:
    series = _as_numeric(series) if not pd.api.types.is_numeric_dtype(series) else series
    clean = series.dropna()
    if len(clean) < 4:
        return None

    q1 = float(clean.quantile(0.25))
    q3 = float(clean.quantile(0.75))
    iqr = q3 - q1
    if iqr == 0:
        return None

    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr

    mask = series.notna() & ((series < lower) | (series > upper))
    outlier_idx = series.index[mask].tolist()

    anomalies = [
        AnomalyEntry(
            row_index=int(idx),
            value=series[idx],
            reason=f"IQR outlier: bounds=[{lower:.2f}, {upper:.2f}]",
        )
        for idx in outlier_idx[:_OUTLIER_CAP]
    ]

    return AnomalyReport(
        column_name=col_name,
        method="iqr",
        anomalies=anomalies,
        stats={
            "q1": round(q1, 4),
            "q3": round(q3, 4),
            "iqr": round(iqr, 4),
            "lower_bound": round(lower, 4),
            "upper_bound": round(upper, 4),
            "detected": len(outlier_idx),
            "sampled": min(len(outlier_idx), _OUTLIER_CAP),
        },
    )


def _detect_rare_categories(series: pd.Series, col_name: str) -> AnomalyReport | None:
    clean = series.dropna().astype(str)
    n = len(clean)
    if n == 0:
        return None

    counts = clean.value_counts()
    threshold = max(_RARE_ABS_THRESHOLD, _RARE_FREQ_THRESHOLD * n)
    rare = counts[counts < threshold]

    if rare.empty:
        return None

    top2 = [
        {"value": str(val), "count": int(cnt), "pct": round(cnt / n * 100, 2)}
        for val, cnt in counts.head(2).items()
    ]

    anomalies = [
        AnomalyEntry(
            row_index=-1,
            value=str(val),
            reason=f"rare category: {cnt} occurrence(s) ({cnt / n * 100:.2f}% of non-null)",
        )
        for val, cnt in rare.items()
    ][:_OUTLIER_CAP]

    return AnomalyReport(
        column_name=col_name,
        method="rare_category",
        anomalies=anomalies,
        stats={
            "total_non_null": n,
            "distinct_values": int(len(counts)),
            "detected": int(len(rare)),
            "sampled": min(int(len(rare)), _OUTLIER_CAP),
            "threshold": round(threshold, 1),
            "top_values": top2,
        },
    )


def _add_llm_comments(reports: list[AnomalyReport]) -> None:
    chain = structured_model(_AnomalyCommentResponse)
    system = load_prompt("anomaly_detector")

    payload = [
        {
            "column_name": r.column_name,
            "method": r.method,
            "stats": r.stats,
            "sample_anomalies": [
                {"value": a.value, "reason": a.reason}
                for a in r.anomalies[:5]
            ],
        }
        for r in reports
    ]

    result: _AnomalyCommentResponse = chain.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ])

    comments = {c.column_name: c.comment for c in result.column_comments}
    for r in reports:
        r.comment = comments.get(r.column_name, "")
