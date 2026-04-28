"""Tests for tools.validate_generated_code (Step 12 AST hardening).

Covers the pre-existing rules (forbidden imports, exec/eval/open/compile)
plus the Step 12 additions: getattr/setattr/delattr/globals/locals/vars
calls, the dunder attribute set, the dunder-prefix attribute walk, the
code-length and AST-node-count limits, and the single-fix(df, col)
top-level function requirement.
"""

from __future__ import annotations

import textwrap

import pytest

from tools import validate_generated_code


def _v(code: str) -> tuple[bool, str]:
    return validate_generated_code(textwrap.dedent(code).strip())


def test_valid_fix_signature_accepted():
    ok, reason = _v(
        """
        def fix(df, col):
            df[col] = df[col].astype(str).str.strip()
        """
    )
    assert ok, reason
    assert reason == "OK"


def test_valid_fix_with_helper_function_accepted():
    ok, reason = _v(
        """
        def _normalise(value):
            return str(value).strip().lower()

        def fix(df, col):
            df[col] = df[col].map(_normalise)
        """
    )
    assert ok, reason


def test_missing_fix_function_rejected():
    ok, reason = _v(
        """
        def helper(df, col):
            df[col] = df[col].astype(str)
        """
    )
    assert not ok
    assert "fix" in reason and "found 0" in reason


def test_duplicate_fix_function_rejected():
    ok, reason = _v(
        """
        def fix(df, col):
            df[col] = df[col].astype(str)

        def fix(df, col):  # noqa: F811
            df[col] = df[col].str.strip()
        """
    )
    assert not ok
    assert "found 2" in reason


@pytest.mark.parametrize(
    "signature",
    [
        "def fix(df):",
        "def fix(df, col, extra):",
        "def fix(df, col, *args):",
        "def fix(df, col, **kwargs):",
        "def fix(df, col=None):",
        "def fix(*, df, col):",
        "def fix(col, df):",
    ],
)
def test_wrong_fix_signature_rejected(signature):
    ok, reason = _v(f"{signature}\n    df[col] = df[col]")
    assert not ok
    assert "signature" in reason


def test_syntax_error_rejected():
    ok, reason = _v("def fix(df, col)\n    df[col] = df[col]")
    assert not ok
    assert "Syntax error" in reason


@pytest.mark.parametrize("module", ["os", "sys", "subprocess", "socket", "ctypes", "shutil"])
def test_forbidden_import_rejected(module):
    ok, reason = _v(
        f"""
        import {module}

        def fix(df, col):
            df[col] = df[col]
        """
    )
    assert not ok
    assert "Forbidden import" in reason


def test_forbidden_from_import_rejected():
    ok, reason = _v(
        """
        from os import system

        def fix(df, col):
            df[col] = df[col]
        """
    )
    assert not ok
    assert "Forbidden import" in reason


@pytest.mark.parametrize(
    "call",
    ["exec(x)", "eval(x)", "compile(x, '', 'exec')", "open('/etc/passwd')", "__import__('os')"],
)
def test_pre_existing_forbidden_calls_rejected(call):
    ok, reason = _v(
        f"""
        def fix(df, col):
            x = 'noop'
            {call}
        """
    )
    assert not ok
    assert "Forbidden call" in reason


@pytest.mark.parametrize(
    "call",
    [
        "globals()",
        "locals()",
        "vars(df)",
        "getattr(df, 'iloc')",
        "setattr(df, 'x', 1)",
        "delattr(df, 'x')",
    ],
)
def test_step12_forbidden_calls_rejected(call):
    ok, reason = _v(
        f"""
        def fix(df, col):
            {call}
        """
    )
    assert not ok
    assert "Forbidden call" in reason


@pytest.mark.parametrize(
    "expr",
    ["df.system('ls')", "df.popen('cat')", "df.run('rm')", "df.Popen('rm')", "df.remove(0)"],
)
def test_pre_existing_forbidden_attr_calls_rejected(expr):
    ok, reason = _v(
        f"""
        def fix(df, col):
            {expr}
        """
    )
    assert not ok
    assert "Forbidden attribute call" in reason


@pytest.mark.parametrize(
    "expr",
    [
        "x = df.__class__",
        "x = df.__bases__",
        "x = df.__subclasses__()",
        "x = df.__globals__",
        "x = df.__builtins__",
        "x = df.__dict__",
        "x = df.__loader__",
        "x = df.__spec__",
        "x = df.__mro__",
        "x = df.__init_subclass__()",
    ],
)
def test_dunder_attribute_access_rejected(expr):
    ok, reason = _v(
        f"""
        def fix(df, col):
            {expr}
        """
    )
    assert not ok
    assert "dunder" in reason.lower() or "Forbidden" in reason


def test_class_bases_subclasses_gadget_rejected():
    ok, reason = _v(
        """
        def fix(df, col):
            x = ().__class__.__bases__[0].__subclasses__()
        """
    )
    assert not ok
    assert "dunder" in reason.lower() or "Forbidden" in reason


def test_arbitrary_dunder_attribute_rejected():
    ok, reason = _v(
        """
        def fix(df, col):
            x = df.__hash__
        """
    )
    assert not ok
    assert "dunder" in reason.lower()


def test_single_underscore_attribute_allowed():
    ok, reason = _v(
        """
        def fix(df, col):
            df[col] = df[col]._values
        """
    )
    assert ok, reason


def test_code_length_limit_enforced():
    body = "    df[col] = df[col]\n" + ("    x = 1\n" * 500)
    ok, reason = _v(f"def fix(df, col):\n{body}")
    assert not ok
    assert "Code too long" in reason


def test_ast_node_count_limit_enforced():
    statements = "; ".join(f"x{i} = {i}" for i in range(250))
    ok, reason = _v(
        f"""
        def fix(df, col):
            {statements}
        """
    )
    assert not ok
    assert "AST too large" in reason


def test_chained_call_pattern_with_safe_methods_allowed():
    ok, reason = _v(
        """
        import re

        def fix(df, col):
            df[col] = df[col].astype(str).str.replace(r'\\s+', ' ', regex=True).str.strip()
        """
    )
    assert ok, reason
