"""Tests for ProfilerAgent's typed-schema LLM call and hallucination guard.

Covers:
- typed DatasetFingerprint output via the schema= path
- statistical fallback on LLM failure (and the guard NOT firing on that path)
- _validate_constraints_against_data rules 1-4 from the plan:
    must_equal_column agreement, no_negatives coercion, format_pattern match,
    unknown columns, date demotion on low parse rate, invalid regex
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from agents_demo.profiler_agent import ProfilerAgent
from state_demo.fingerprint_schema import DatasetFingerprint
from state_demo.pipeline_state import PipelineState


def _empty_fingerprint(**overrides: Any) -> DatasetFingerprint:
    base = {
        "domain": "test",
        "language": "english",
        "id_columns": [],
        "numerical_columns": [],
        "categorical_columns": [],
        "date_columns": [],
        "sparse_columns": [],
        "likely_duplicate_pairs": [],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    base.update(overrides)
    return DatasetFingerprint(**base)


def _profiler_corrections(state: PipelineState) -> list[dict[str, Any]]:
    return [i for i in state.cross_agent_insights if i.get("type") == "profiler_self_correction"]


@pytest.fixture
def df_simple() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rata": ["1", "2", "3", "4", "5"],
            "ente": ["RM", "MI", "BA", "RM", "MI"],
            "imposta": ["100.5", "200.0", "300.5", "400.0", "500.5"],
            "descrizione": ["alpha", "beta", "gamma", "delta", "epsilon"],
        }
    )


def test_profiler_writes_fingerprint_when_llm_succeeds(
    df_simple: pd.DataFrame,
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    state.df_raw = df_simple
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        domain="test domain",
        language="italian",
        numerical_columns=["imposta"],
        categorical_columns=["ente"],
        column_descriptions={"rata": "row index"},
    )

    ProfilerAgent(state).run("profile")

    fp = state.dataset_fingerprint
    assert fp["domain"] == "test domain"
    assert fp["language"] == "italian"
    assert fp["numerical_columns"] == ["imposta"]
    assert fp["categorical_columns"] == ["ente"]
    assert _profiler_corrections(state) == []


def test_profiler_falls_back_to_statistical_on_llm_error(
    df_simple: pd.DataFrame,
    state: PipelineState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state.df_raw = df_simple

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("LLM unavailable")

    from agents_demo.base_agent import BaseAgent

    monkeypatch.setattr(BaseAgent, "call_llm_json", _boom)

    ProfilerAgent(state).run("profile")

    fp = state.dataset_fingerprint
    assert "numerical_columns" in fp
    assert "imposta" in fp["numerical_columns"]
    assert _profiler_corrections(state) == []


def test_guard_drops_must_equal_column_with_low_agreement(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame(
        {
            "col_a": ["1", "2", "3", "4", "5"],
            "col_b": ["1", "2", "9", "9", "9"],
        }
    )
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        column_constraints=[
            {
                "column": "col_a",
                "type": "must_equal_column",
                "other_column": "col_b",
                "description": "should be denormalised duplicates",
            }
        ],
    )

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["column_constraints"] == []
    corrections = _profiler_corrections(state)
    assert any(c["subject"] == "must_equal_column" and c["column"] == "col_a" for c in corrections)


def test_guard_keeps_must_equal_column_with_high_agreement(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"a": ["x", "y", "z", "w"], "b": ["x", "y", "z", "w"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        column_constraints=[
            {"column": "a", "type": "must_equal_column", "other_column": "b", "description": ""}
        ],
    )

    ProfilerAgent(state).run("profile")

    assert len(state.dataset_fingerprint["column_constraints"]) == 1
    assert _profiler_corrections(state) == []


def test_guard_drops_no_negatives_on_text_column(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"descrizione": ["alpha", "beta", "gamma", "delta"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        column_constraints=[
            {"column": "descrizione", "type": "no_negatives", "description": "amounts"}
        ],
    )

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["column_constraints"] == []
    corrections = _profiler_corrections(state)
    assert any(c["subject"] == "no_negatives" and c["column"] == "descrizione" for c in corrections)


def test_guard_drops_format_pattern_with_zero_match(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"text_col": ["hello", "world", "foo", "bar"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        column_constraints=[
            {
                "column": "text_col",
                "type": "format_pattern",
                "pattern": r"^\d{6}$",
                "description": "YYYYMM period codes",
            }
        ],
    )

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["column_constraints"] == []
    corrections = _profiler_corrections(state)
    assert any(c["subject"] == "format_pattern" and c["column"] == "text_col" for c in corrections)


def test_guard_drops_format_pattern_with_invalid_regex(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"text_col": ["abc", "def", "ghi"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        column_constraints=[
            {
                "column": "text_col",
                "type": "format_pattern",
                "pattern": "[invalid(regex",
                "description": "broken",
            }
        ],
    )

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["column_constraints"] == []
    corrections = _profiler_corrections(state)
    matching = [c for c in corrections if c["subject"] == "format_pattern"]
    assert matching
    assert "invalid regex" in matching[0]["detail"]


def test_guard_drops_unknown_columns_from_typed_lists(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"real": ["1", "2", "3"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        numerical_columns=["real", "phantom"],
        categorical_columns=["nonexistent"],
    )

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["numerical_columns"] == ["real"]
    assert state.dataset_fingerprint["categorical_columns"] == []
    corrections = _profiler_corrections(state)
    dropped_columns = {c["column"] for c in corrections if c["subject"] == "unknown_column"}
    assert dropped_columns == {"phantom", "nonexistent"}


def test_guard_demotes_date_column_with_low_parse_rate(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"fake_date": ["alpha", "beta", "gamma", "delta", "epsilon"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(date_columns=["fake_date"])

    ProfilerAgent(state).run("profile")

    fp = state.dataset_fingerprint
    assert fp["date_columns"] == []
    assert "fake_date" in fp["categorical_columns"]
    corrections = _profiler_corrections(state)
    assert any(c["subject"] == "date_demotion" and c["column"] == "fake_date" for c in corrections)


def test_guard_keeps_date_column_with_high_parse_rate(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"d": ["2024-01-01", "2024-02-15", "2024-03-30", "2024-04-10"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(date_columns=["d"])

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["date_columns"] == ["d"]
    assert _profiler_corrections(state) == []


def test_guard_drops_constraint_targeting_unknown_column(
    state: PipelineState,
    monkeypatch_llm: dict[str, Any],
) -> None:
    df = pd.DataFrame({"a": ["1", "2", "3"]})
    state.df_raw = df
    monkeypatch_llm["call_llm_json"] = _empty_fingerprint(
        column_constraints=[{"column": "ghost", "type": "no_negatives", "description": "x"}],
    )

    ProfilerAgent(state).run("profile")

    assert state.dataset_fingerprint["column_constraints"] == []
    corrections = _profiler_corrections(state)
    assert any(c["subject"] == "unknown_column" and c["column"] == "ghost" for c in corrections)
