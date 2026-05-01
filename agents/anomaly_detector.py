"""Detects numeric outliers (IQR method) and rare categorical values per column using pure
pandas/numpy, then sends the aggregated findings to gpt-4o-mini for a one-sentence
explanatory comment per column."""
from __future__ import annotations

import json

import pandas as pd
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import AnomalyEntry, AnomalyReport
from state import PipelineState
from utils.prompts import load_prompt

_RARE_FREQ_THRESHOLD = 0.01  # below 1% of non-null rows
_RARE_ABS_THRESHOLD = 3      # or fewer than 3 absolute occurrences
_OUTLIER_CAP = 50            # max anomaly entries stored per column


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

    for col in df.columns:
        series = df[col]
        clean = series.dropna()
        if len(clean) == 0:
            continue

        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            report = _detect_numeric_outliers(series, col)
        elif (
            pd.api.types.is_string_dtype(series)
            or pd.api.types.is_object_dtype(series)
            or pd.api.types.is_categorical_dtype(series)
        ):
            report = _detect_rare_categories(series, col)
        else:
            continue

        if report is not None and report.anomalies:
            reports.append(report)

    if reports:
        _add_llm_comments(reports)

    return state.model_copy(update={"anomaly_reports": reports})


def _detect_numeric_outliers(series: pd.Series, col_name: str) -> AnomalyReport | None:
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
            "outlier_count": len(outlier_idx),
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
    ]

    return AnomalyReport(
        column_name=col_name,
        method="rare_category",
        anomalies=anomalies,
        stats={
            "total_non_null": n,
            "distinct_values": int(len(counts)),
            "rare_values_count": int(len(rare)),
            "threshold": round(threshold, 1),
            "top_values": top2,
        },
    )


def _add_llm_comments(reports: list[AnomalyReport]) -> None:
    chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(_AnomalyCommentResponse)
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
