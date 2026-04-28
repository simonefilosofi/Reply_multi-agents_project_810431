"""Tests for CodeValidatorAgent and the Step 12 sandbox refactor.

Direct sandbox tests cover ``run_in_subprocess_fallback`` cross-platform:
benign-fix execution, runtime-error capture, user-print isolation. Dispatcher
tests verify that ``run_sandboxed`` falls back to the subprocess path when
Docker is unavailable and warns only once. The Docker path itself is
exercised by ``test_run_in_docker_benign_fix`` under the ``docker`` mark
(skipped when ``docker.from_env().ping()`` fails). Resource-limit
enforcement is tested by ``test_subprocess_kills_memory_hog`` on POSIX
hosts only; on Windows the rlimit calls are silently skipped per the plan.

Agent-level integration tests use the monkeypatched LLM stubs from
``tests/conftest.py`` to drive a deterministic filter / fix / review
sequence and assert that benign fixes are applied via the subprocess
fallback while malicious code is rejected at the AST layer before any
sandbox invocation.
"""

from __future__ import annotations

import sys
from typing import Any

import pandas as pd
import pytest

import tools_code_validator
from agents_demo.code_validator_agent import CodeValidatorAgent
from state_demo import settings as global_settings
from state_demo.pipeline_state import PipelineState
from tools_code_validator import (
    _parse_mem_to_bytes,
    _reset_docker_probe,
    run_in_subprocess_fallback,
    run_sandboxed,
)


@pytest.fixture(autouse=True)
def _reset_probe_between_tests():
    _reset_docker_probe()
    yield
    _reset_docker_probe()


def _df_with_placeholders() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": ["alice", "bob", "carol", "dave", "eve"],
            "salary": ["1000", "-999", "2000", "-999", "3000"],
        }
    )


def test_subprocess_fallback_benign_fix():
    df = _df_with_placeholders()
    code = (
        "def fix(df, col):\n"
        "    df[col] = df[col].astype(str).str.replace('-999', 'NA', regex=False)\n"
    )
    ok, result = run_in_subprocess_fallback(df, "salary", code, global_settings)
    assert ok, result
    assert isinstance(result, pd.DataFrame)
    assert list(result["salary"]) == ["1000", "NA", "2000", "NA", "3000"]


def test_subprocess_fallback_runtime_error():
    df = _df_with_placeholders()
    code = "def fix(df, col):\n    raise ValueError('boom')\n"
    ok, result = run_in_subprocess_fallback(df, "salary", code, global_settings)
    assert not ok
    assert isinstance(result, str)
    assert "ValueError" in result and "boom" in result


def test_subprocess_fallback_no_fix_function_returns_error():
    df = _df_with_placeholders()
    code = "def helper(df, col):\n    pass\n"
    ok, result = run_in_subprocess_fallback(df, "salary", code, global_settings)
    assert not ok
    assert isinstance(result, str)
    assert "fix" in result.lower()


def test_subprocess_fallback_user_print_does_not_corrupt_output():
    df = _df_with_placeholders()
    code = (
        "def fix(df, col):\n"
        "    print('debug line one')\n"
        "    print('debug line two')\n"
        "    df[col] = df[col].astype(str).str.upper()\n"
    )
    ok, result = run_in_subprocess_fallback(df, "name", code, global_settings)
    assert ok, result
    assert list(result["name"]) == ["ALICE", "BOB", "CAROL", "DAVE", "EVE"]


def test_run_sandboxed_dispatches_to_subprocess_when_no_docker(monkeypatch):
    monkeypatch.setattr(tools_code_validator, "_is_docker_available", lambda: False)
    df = _df_with_placeholders()
    code = "def fix(df, col):\n    df[col] = df[col].astype(str).str.lower()\n"
    ok, result = run_sandboxed(df, "name", code, global_settings)
    assert ok, result
    assert list(result["name"]) == ["alice", "bob", "carol", "dave", "eve"]


def test_run_sandboxed_warns_only_once(monkeypatch, caplog):
    monkeypatch.setattr(tools_code_validator, "_is_docker_available", lambda: False)
    df = _df_with_placeholders()
    code = "def fix(df, col):\n    df[col] = df[col]\n"
    with caplog.at_level("WARNING", logger="tools_code_validator"):
        run_sandboxed(df, "name", code, global_settings)
        run_sandboxed(df, "name", code, global_settings)
        run_sandboxed(df, "name", code, global_settings)
    fallback_warnings = [r for r in caplog.records if "subprocess fallback" in r.message]
    assert len(fallback_warnings) == 1


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("512m", 512 * 1024**2),
        ("512mb", 512 * 1024**2),
        ("1g", 1024**3),
        ("1G", 1024**3),
        ("256k", 256 * 1024),
        ("4096", 4096),
    ],
)
def test_parse_mem_to_bytes(raw, expected):
    assert _parse_mem_to_bytes(raw) == expected


def _gap_issue(column: str, filter_expr: str) -> dict[str, Any]:
    return {
        "column": column,
        "type": "format_issue",
        "detail": f"placeholder values in '{column}'",
        "severity": "medium",
        "filter": filter_expr,
    }


def test_agent_applies_benign_fix_via_subprocess(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_code_validator, "_is_docker_available", lambda: False)
    monkeypatch.setattr(CodeValidatorAgent, "_GENERATED_FIXES_DIR", str(tmp_path))

    state = PipelineState()
    state.df_raw = _df_with_placeholders()
    state.df_cleaned = state.df_raw.copy()
    state.gap_issues = [_gap_issue("salary", "df['salary'] == '-999'")]

    canned_text = iter(
        [
            "def fix(df, col):\n"
            "    df[col] = df[col].astype(str).str.replace('-999', '0', regex=False)\n"
        ]
    )
    canned_json = iter([{"approved": True, "reason": "looks safe"}])

    monkeypatch.setattr(
        CodeValidatorAgent,
        "call_llm",
        lambda self, user, max_tokens=4096: next(canned_text),
    )
    monkeypatch.setattr(
        CodeValidatorAgent,
        "call_llm_json",
        lambda self, user, max_tokens=4096, required_keys=None, schema=None: next(canned_json),
    )

    agent = CodeValidatorAgent(state)
    agent.run("")

    auto_fixes = [f for f in state.fix_log if f.get("action") == "auto_fixed_by_llm"]
    assert len(auto_fixes) == 1
    assert auto_fixes[0]["column"] == "salary"
    assert auto_fixes[0]["rows_affected"] == 2
    assert list(state.df_cleaned["salary"]) == ["1000", "0", "2000", "0", "3000"]
    assert state.human_review_items == []


def test_agent_flags_malicious_code_via_ast_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(tools_code_validator, "_is_docker_available", lambda: False)
    monkeypatch.setattr(CodeValidatorAgent, "_GENERATED_FIXES_DIR", str(tmp_path))

    state = PipelineState()
    state.df_raw = _df_with_placeholders()
    state.df_cleaned = state.df_raw.copy()
    state.gap_issues = [_gap_issue("salary", "df['salary'] == '-999'")]

    malicious = "import os\ndef fix(df, col):\n    os.system('rm -rf /')\n"
    monkeypatch.setattr(
        CodeValidatorAgent,
        "call_llm",
        lambda self, user, max_tokens=4096: malicious,
    )
    monkeypatch.setattr(
        CodeValidatorAgent,
        "call_llm_json",
        lambda self, user, max_tokens=4096, required_keys=None, schema=None: {"approved": True},
    )

    sandbox_calls: list[Any] = []
    monkeypatch.setattr(
        tools_code_validator,
        "run_sandboxed",
        lambda *args, **kwargs: sandbox_calls.append(args) or (False, "should not run"),
    )

    agent = CodeValidatorAgent(state)
    agent.run("")

    assert sandbox_calls == []
    assert [f for f in state.fix_log if f.get("action") == "auto_fixed_by_llm"] == []
    assert len(state.human_review_items) == 1
    assert state.human_review_items[0]["column"] == "salary"
    assert "AST validation failed" in state.human_review_items[0]["last_error"]


def test_agent_with_no_gap_issues_is_noop():
    state = PipelineState()
    state.df_raw = _df_with_placeholders()
    state.df_cleaned = state.df_raw.copy()
    state.gap_issues = []

    agent = CodeValidatorAgent(state)
    agent.run("")

    assert state.fix_log == []
    assert state.human_review_items == []


def test_agent_skips_gap_issue_with_unknown_column():
    state = PipelineState()
    state.df_raw = _df_with_placeholders()
    state.df_cleaned = state.df_raw.copy()
    state.gap_issues = [_gap_issue("nonexistent", "df['salary'] == '-999'")]

    agent = CodeValidatorAgent(state)
    agent.run("")

    assert state.fix_log == []
    assert state.human_review_items == []
    skip_logs = [
        e
        for e in state.agent_log
        if e["agent"] == "code_validator" and "not in DataFrame" in e["message"]
    ]
    assert len(skip_logs) == 1


def _docker_unavailable() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return False
    except Exception:
        return True


@pytest.mark.docker
@pytest.mark.skipif(_docker_unavailable(), reason="Docker daemon not reachable")
def test_run_in_docker_benign_fix():
    from tools_code_validator import run_in_docker

    df = _df_with_placeholders()
    code = (
        "def fix(df, col):\n"
        "    df[col] = df[col].astype(str).str.replace('-999', 'NA', regex=False)\n"
    )
    ok, result = run_in_docker(df, "salary", code, global_settings)
    assert ok, result
    assert isinstance(result, pd.DataFrame)
    assert list(result["salary"]) == ["1000", "NA", "2000", "NA", "3000"]


@pytest.mark.skipif(sys.platform == "win32", reason="resource.setrlimit is POSIX-only")
def test_subprocess_kills_memory_hog():
    df = _df_with_placeholders()
    code = "def fix(df, col):\n    big = [0] * (300 * 1024 * 1024)\n    df[col] = str(len(big))\n"
    ok, result = run_in_subprocess_fallback(df, "name", code, global_settings)
    assert not ok
    assert isinstance(result, str)
