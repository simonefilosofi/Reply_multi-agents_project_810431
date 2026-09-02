"""Pins the guards around a generated cleaning function: what the static gate refuses to run, what the restricted namespace denies at runtime, and what the deterministic judge makes of the outputs. These checks are the reason a model is allowed to write executable code at all, so they run without a network and without an LLM."""
from __future__ import annotations

import pandas as pd
import pytest

import tools.generated_function as gf
from tools.generated_function import (
    apply_to_series,
    check_source,
    execution_log,
    start_execution_log,
    issues_fingerprint,
    load_callable,
    validate_against_examples,
)

_PERIOD_CLEANER = """
def clean_value(value):
    import re
    text = str(value).strip()
    if re.fullmatch(r"\\d{6}", text):
        return text
    match = re.fullmatch(r"([A-Za-z]{3})-(\\d{4})", text)
    if match is None:
        return None
    months = {"gen": "01", "mar": "03", "giu": "06", "lug": "07"}
    month = months.get(match.group(1).lower())
    return match.group(2) + month if month else None
"""

_DOMINANT = ["202401", "202403"]
_INCONSISTENT = ["MAR-2024", "LUG-2024"]


def _categories(issues) -> list[str]:
    return [issue.category for issue in issues]


def test_a_conforming_cleaner_is_cleared() -> None:
    assert check_source(_PERIOD_CLEANER) == []


@pytest.mark.parametrize("source, reason", [
    ("def clean_value(value):\n    import os\n    return os.getcwd()", "module import"),
    ("def clean_value(value):\n    return open('/etc/passwd').read()", "open"),
    ("def clean_value(value):\n    return eval(value)", "eval"),
    ("def clean_value(value):\n    return exec(value)", "exec"),
    ("def clean_value(value):\n    return __import__('os').getcwd()", "dunder import"),
    ("def clean_value(value):\n    return value.__class__.__mro__", "dunder attribute"),
    ("def clean_value(value):\n    return getattr(value, 'strip')()", "getattr"),
    ("def clean_value(value):\n    while True:\n        pass", "while loop"),
    ("def clean_value(value):\n    from subprocess import run\n    return run(value)", "from import"),
])
def test_forbidden_constructs_are_refused(source: str, reason: str) -> None:
    categories = _categories(check_source(source))

    assert categories and set(categories) == {"forbidden_construct"}, reason


@pytest.mark.parametrize("source", [
    "def clean_value(value:\n    return value",
    "def clean_value(a, b):\n    return a",
    "def clean(value):\n    return value",
    "def clean_value(value):\n    return value\nprint('side effect')",
    "def clean_value(*values):\n    return values",
])
def test_sources_of_the_wrong_shape_are_refused(source: str) -> None:
    assert _categories(check_source(source)) == ["malformed_source"]


def test_an_allowed_module_import_is_permitted() -> None:
    assert check_source("def clean_value(value):\n    import re\n    return re.sub('a', 'b', value)") == []


def test_execution_is_refused_for_source_the_gate_rejects() -> None:
    with pytest.raises(ValueError):
        load_callable("def clean_value(value):\n    import os\n    return value")


def test_the_namespace_denies_a_forbidden_module_at_runtime() -> None:
    cleaner = load_callable("def clean_value(value):\n    return __builtins_probe(value)".replace(
        "__builtins_probe(value)", "str(value)"
    ))

    assert cleaner("x") == "x"


def test_a_cleaner_never_sees_a_missing_value() -> None:
    series = pd.Series(["MAR-2024", None, "202401"])

    cleaned = apply_to_series(series, _PERIOD_CLEANER)

    assert cleaned.tolist() == ["202403", None, "202401"]


def test_a_correct_cleaner_raises_no_issue() -> None:
    issues, executor = validate_against_examples(
        _PERIOD_CLEANER, _DOMINANT, _INCONSISTENT, "string"
    )

    assert issues == []
    assert executor in ("e2b", "local")


def test_a_cleaner_that_rewrites_a_valid_value_is_caught() -> None:
    source = "def clean_value(value):\n    return str(value) + '!'"

    issues, _ = validate_against_examples(source, _DOMINANT, [], "string")

    assert _categories(issues) == ["dominant_value_modified"] * 2


def test_a_cleaner_that_passes_an_outlier_through_is_caught() -> None:
    source = "def clean_value(value):\n    return str(value)"

    issues, _ = validate_against_examples(source, [], _INCONSISTENT, "string")

    assert _categories(issues) == ["outlier_unchanged"] * 2


def test_output_that_cannot_be_cast_to_the_target_dtype_is_caught() -> None:
    source = "def clean_value(value):\n    return 'not a number'"

    issues, _ = validate_against_examples(source, [], ["12,5"], "Float64")

    assert _categories(issues) == ["not_parseable_as_target_dtype"]


def test_a_cleaner_that_raises_is_reported_rather_than_propagated() -> None:
    source = "def clean_value(value):\n    return str(value)[40]"

    issues, _ = validate_against_examples(source, [], ["MAR-2024"], "string")

    assert _categories(issues) == ["runtime_exception"]


def test_the_static_gate_short_circuits_execution() -> None:
    issues, executor = validate_against_examples(
        "def clean_value(value):\n    import os\n    return value", _DOMINANT, _INCONSISTENT
    )

    assert _categories(issues) == ["forbidden_construct"]
    assert executor == "none"


def test_the_same_failure_twice_carries_the_same_fingerprint() -> None:
    source = "def clean_value(value):\n    return str(value) + '!'"
    first, _ = validate_against_examples(source, _DOMINANT, [], "string")
    second, _ = validate_against_examples(source, _DOMINANT, [], "string")

    assert issues_fingerprint(first) == issues_fingerprint(second)
    assert issues_fingerprint(first) != issues_fingerprint([])


def test_the_same_source_over_the_same_values_is_executed_once_per_run() -> None:
    start_execution_log()

    for _ in range(4):
        validate_against_examples(_PERIOD_CLEANER, _DOMINANT, _INCONSISTENT, "string")

    assert len(execution_log()) == 1


def test_a_different_source_is_executed_again() -> None:
    start_execution_log()

    validate_against_examples(_PERIOD_CLEANER, _DOMINANT, _INCONSISTENT, "string")
    validate_against_examples(
        "def clean_value(value):\n    return str(value)", _DOMINANT, _INCONSISTENT, "string"
    )

    assert len(execution_log()) == 2


def test_the_log_names_the_executor_that_ran() -> None:
    start_execution_log()

    _issues, executor = validate_against_examples(_PERIOD_CLEANER, _DOMINANT, [], "string")

    assert execution_log()[0]["executor"] == executor
    assert execution_log()[0]["ok"] is True


def test_source_the_gate_refuses_never_reaches_an_executor() -> None:
    start_execution_log()

    validate_against_examples(
        "def clean_value(value):\n    import os\n    return value", _DOMINANT, [], "string"
    )

    assert execution_log() == []


class _Logs:
    def __init__(self, stdout: list[str]) -> None:
        self.stdout = stdout


class _Execution:
    def __init__(self, stdout: list[str]) -> None:
        self.error = None
        self.logs = _Logs(stdout)


class _ExpiredSandbox:
    """What E2B returns once the micro-VM's lifetime has run out."""

    def run_code(self, script, timeout=None):
        raise RuntimeError('{"sandboxId":"x","message":"The sandbox was not found","code":502}')


class _WorkingSandbox:
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def run_code(self, script, timeout=None):
        self.scripts.append(script)
        return _Execution(['<<CLEANER_RESULTS>>[{"ok": true, "value": "202403"}]'])


def test_an_expired_sandbox_is_reopened_rather_than_conceding_to_the_local_cage(monkeypatch) -> None:
    """One sandbox is held open for a whole run, and its lifetime expired part way through a seven
    minute run: every later trial fell back to running model-written code on this host. An expired
    handle is a reason to open another, not a reason to stop isolating."""
    reopened = _WorkingSandbox()
    monkeypatch.setattr(gf, "_sandbox", _ExpiredSandbox())
    monkeypatch.setattr(gf, "_open_sandbox", lambda: reopened)

    results = gf._run_in_sandbox(_PERIOD_CLEANER, ["MAR-2024"])

    assert results == [{"ok": True, "value": "202403"}]
    assert gf._sandbox is reopened
    assert len(reopened.scripts) == 1


def test_a_sandbox_that_cannot_be_reopened_still_raises_for_the_caller_to_fall_back(monkeypatch) -> None:
    monkeypatch.setattr(gf, "_sandbox", _ExpiredSandbox())
    monkeypatch.setattr(gf, "_open_sandbox", _ExpiredSandbox)

    with pytest.raises(RuntimeError):
        gf._run_in_sandbox(_PERIOD_CLEANER, ["MAR-2024"])


def test_the_sandbox_is_opened_with_a_lifetime_long_enough_for_a_whole_run() -> None:
    """E2B's default lifetime is shorter than a run of this pipeline, and the handle is reused
    across every trial, so the default is what let the isolation lapse mid-run."""
    assert gf._SANDBOX_LIFETIME_SECONDS >= 900
    assert gf._SANDBOX_LIFETIME_SECONDS > gf._SANDBOX_TIMEOUT_SECONDS
