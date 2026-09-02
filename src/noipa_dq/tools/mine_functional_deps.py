"""Deterministic functional-dependency miner behind the NaN-imputation hints the Format & Consistency agent emits. Scores single and pair predictors on purity (agreement with the key's dominant value, so one outlier cannot disqualify a sound dependency) and coverage (share of gaps reached), gating on coverage before comparison so a predictor pure on a handful of rows cannot beat one that reaches the gaps. The emitted lookup carries only keys with a decisive value, so a key that genuinely changes partway through the data costs its own rows rather than the whole column. Raw and normalised key paths are both tried; raw wins ties."""
from __future__ import annotations

import pandas as pd

from noipa_dq.models import ImputationHint
from noipa_dq.tools.cross_column_checks import period_key


_DOMINANT_THRESHOLD = 0.95
_KEY_DOMINANCE = 0.95
_COVERAGE_THRESHOLD = 0.5
_PAIR_SEARCH_CAP = 8
_PAIR_KEY_DELIMITER = "|"


def mine_functional_deps(
    df: pd.DataFrame,
    target_columns: list[str],
    candidate_predictors: dict[str, list[str]],
    coverage_threshold: float = _COVERAGE_THRESHOLD,
    dominant_threshold: float = _DOMINANT_THRESHOLD,
    pair_search_cap: int = _PAIR_SEARCH_CAP,
) -> dict[str, ImputationHint]:
    hints: dict[str, ImputationHint] = {}
    for target in target_columns:
        if target not in df.columns:
            continue
        nan_mask = df[target].isna()
        n_nan = int(nan_mask.sum())
        if n_nan == 0:
            continue
        candidates = [
            c for c in candidate_predictors.get(target, [])
            if c in df.columns and c != target
        ]
        if not candidates:
            continue
        best: tuple[ImputationHint, tuple[float, float, int]] | None = None

        def consider(candidate: ImputationHint | None, path: str) -> None:
            nonlocal best
            if candidate is None or candidate.coverage < coverage_threshold:
                return
            best = _maybe_swap(best, candidate, path)

        for predictor in candidates:
            for path in ("raw", "normalized"):
                consider(
                    _try_single(df, target, predictor, path, nan_mask, n_nan, dominant_threshold),
                    path,
                )
        if len(candidates) <= pair_search_cap:
            for i in range(len(candidates)):
                for j in range(i + 1, len(candidates)):
                    for path in ("raw", "normalized"):
                        consider(
                            _try_pair(
                                df, target, candidates[i], candidates[j],
                                path, nan_mask, n_nan, dominant_threshold,
                            ),
                            path,
                        )
        if best is not None:
            hints[target] = best[0]
    return hints


def _unambiguous_mapping(grouped, dominant) -> dict:
    share = grouped.apply(lambda values: values.value_counts().iloc[0] / len(values))
    decisive = share >= _KEY_DOMINANCE
    return {
        str(key): _jsonable(value)
        for key, value in dominant[decisive].items()
    }


def _maybe_swap(
    current: tuple[ImputationHint, tuple[float, float, int]] | None,
    candidate: ImputationHint | None,
    path: str,
) -> tuple[ImputationHint, tuple[float, float, int]] | None:
    if candidate is None:
        return current
    score = (candidate.purity, candidate.coverage, 1 if path == "raw" else 0)
    if current is None or score > current[1]:
        return (candidate, score)
    return current


def _try_single(
    df: pd.DataFrame,
    target: str,
    predictor: str,
    path: str,
    nan_mask: pd.Series,
    n_nan: int,
    dominant_threshold: float,
) -> ImputationHint | None:
    pair = df[[predictor, target]].dropna()
    if pair.empty:
        return None
    keys = _normalize(pair[predictor], path).astype(str)
    grouped = pair[target].groupby(keys)
    if not len(grouped):
        return None
    dominant = grouped.agg(lambda values: values.value_counts().idxmax())
    purity = float((pair[target] == keys.map(dominant)).mean())
    if purity < dominant_threshold:
        return None
    mapping = _unambiguous_mapping(grouped, dominant)
    if not mapping:
        return None
    pred_for_nans = _normalize(df.loc[nan_mask, predictor], path).astype(str)
    coverable = df.loc[nan_mask, predictor].notna() & pred_for_nans.isin(mapping.keys())
    coverage = float(coverable.sum() / n_nan) if n_nan else 0.0
    if coverage <= 0:
        return None
    return ImputationHint(
        target_column=target,
        predictor_columns=[predictor],
        mapping=mapping,
        path=path,
        purity=purity,
        coverage=coverage,
        confidence="strict" if purity == 1.0 else "dominant",
        rationale=(
            f"{predictor} -> {target}: purity={purity:.2f}, coverage={coverage:.2f} "
            f"on path '{path}'"
        ),
    )


def _try_pair(
    df: pd.DataFrame,
    target: str,
    p1: str,
    p2: str,
    path: str,
    nan_mask: pd.Series,
    n_nan: int,
    dominant_threshold: float,
) -> ImputationHint | None:
    sub = df[[p1, p2, target]].dropna()
    if sub.empty:
        return None
    k1 = _normalize(sub[p1], path).astype(str)
    k2 = _normalize(sub[p2], path).astype(str)
    grouped = sub[target].groupby([k1, k2]).agg(["nunique", "first"])
    if grouped.empty:
        return None
    pure = grouped["nunique"] == 1
    purity = float(pure.sum() / len(grouped))
    if purity < dominant_threshold:
        return None
    mapping = {
        f"{a}{_PAIR_KEY_DELIMITER}{b}": _jsonable(v)
        for (a, b), v in grouped.loc[pure, "first"].items()
    }
    rows_nan = df.loc[nan_mask]
    n1 = _normalize(rows_nan[p1], path).astype(str)
    n2 = _normalize(rows_nan[p2], path).astype(str)
    composite = n1.str.cat(n2, sep=_PAIR_KEY_DELIMITER)
    coverable = rows_nan[p1].notna() & rows_nan[p2].notna() & composite.isin(mapping.keys())
    coverage = float(coverable.sum() / n_nan) if n_nan else 0.0
    if coverage <= 0:
        return None
    return ImputationHint(
        target_column=target,
        predictor_columns=[p1, p2],
        mapping=mapping,
        path=path,
        purity=purity,
        coverage=coverage,
        confidence="strict" if purity == 1.0 else "dominant",
        rationale=(
            f"({p1},{p2}) -> {target}: purity={purity:.2f}, coverage={coverage:.2f} "
            f"on path '{path}', pair-keys joined with '{_PAIR_KEY_DELIMITER}'"
        ),
    )


def _normalize(series: pd.Series, path: str) -> pd.Series:
    s = period_key(series).astype("string")
    if path == "normalized":
        s = s.str.lower().str.strip()
    return s


def _jsonable(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value
