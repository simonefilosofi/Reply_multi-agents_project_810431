"""Execution and validation of the per-column cleaning functions the Unified Remediation agent generates. A generated cleaner is a pure scalar transform named clean_value, so it can neither change the row count nor reach another column: half of the post-fix invariants hold by construction rather than by check. Three layers guard the rest. check_source reads the source and rejects it before anything runs, so what reaches the interpreter is already known to be free of imports outside a small allowlist, of eval, exec, open and attribute access into dunders. validate_against_examples then executes the never-yet-run code inside an E2B sandbox, which isolates the host but does not restrain the code, and falls back to the local cage when no key or no network is available; the sandbox only executes, while the judgement of what the outputs mean stays here and stays deterministic. load_callable finally runs the approved source locally over the full column, in a namespace whose builtins are a whitelist and whose import hook admits only the allowed modules."""
from __future__ import annotations

import ast
import json
import os
from typing import Any, Callable, Iterable

import pandas as pd

from models import CleanerIssue

FUNCTION_NAME = "clean_value"

_ALLOWED_MODULES = frozenset({"re", "datetime", "decimal", "math"})
_FORBIDDEN_NAMES = frozenset({
    "eval", "exec", "open", "compile", "input", "breakpoint", "exit", "quit",
    "__import__", "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "memoryview", "help",
})
_SAFE_BUILTIN_NAMES = (
    "abs", "all", "any", "bool", "chr", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "hash", "int", "isinstance", "issubclass",
    "iter", "len", "list", "map", "max", "min", "next", "ord", "pow", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple",
    "zip", "ArithmeticError", "AttributeError", "Exception", "IndexError",
    "KeyError", "OverflowError", "StopIteration", "TypeError", "ValueError",
    "ZeroDivisionError",
)
_SANDBOX_MARKER = "<<CLEANER_RESULTS>>"
_SANDBOX_TIMEOUT_SECONDS = 20


def check_source(source: str) -> list[CleanerIssue]:
    """Reads the source and reports every reason it must not run. An empty list is the only
    clearance to execute; callers re-run this immediately before execution rather than trusting
    a clearance obtained earlier."""
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [CleanerIssue(
            category="malformed_source",
            message=f"the source does not parse: {error}",
            expected_behavior="return a single valid Python function definition.",
        )]

    issues = _check_shape(tree)
    issues.extend(_check_constructs(tree))
    return issues


def load_callable(source: str) -> Callable[[Any], str | None]:
    """Compiles the source in a namespace holding only whitelisted builtins and an import hook
    limited to the allowed modules. Raises when the source has not been cleared by check_source."""
    issues = check_source(source)
    if issues:
        raise ValueError(f"refusing to execute a generated cleaner: {issues[0].message}")
    namespace: dict[str, Any] = {"__builtins__": _restricted_builtins()}
    exec(compile(source, "<generated_cleaner>", "exec"), namespace)
    cleaner = namespace.get(FUNCTION_NAME)
    if not callable(cleaner):
        raise ValueError(f"the source defines no callable named {FUNCTION_NAME!r}")
    return cleaner


def apply_to_series(series: pd.Series, source: str) -> pd.Series:
    """Runs an approved cleaner over a whole column, locally. Missing values are never handed to
    the cleaner, so a generated function never has to defend against NaN."""
    cleaner = load_callable(source)
    return series.map(lambda value: value if pd.isna(value) else cleaner(value))


def validate_against_examples(
    source: str,
    dominant_values: Iterable[Any],
    inconsistent_values: Iterable[Any],
    target_dtype: str = "",
) -> tuple[list[CleanerIssue], str]:
    """Executes the cleaner over the column's own evidence and reports what the outputs mean.
    Returns the issues alongside the name of the executor that ran the code."""
    blocking = check_source(source)
    if blocking:
        return blocking, "none"

    dominant = [_as_scalar(value) for value in dominant_values]
    inconsistent = [_as_scalar(value) for value in inconsistent_values]
    results, executor = run_on_values(source, dominant + inconsistent)
    _executions.append({"executor": executor, "ok": True, "values": len(dominant) + len(inconsistent)})

    issues = _judge(dominant, results[: len(dominant)], expected_unchanged=True, dtype=target_dtype)
    issues.extend(
        _judge(inconsistent, results[len(dominant):], expected_unchanged=False, dtype=target_dtype)
    )
    return issues, executor


def run_on_values(source: str, values: list[str | None]) -> tuple[list[dict], str]:
    """Executes the cleaner over a handful of values, preferring the sandbox. The fallback exists
    so a missing key or a dropped connection degrades the isolation of a first run rather than
    stopping the pipeline."""
    if os.getenv("E2B_API_KEY"):
        try:
            return _run_in_sandbox(source, values), "e2b"
        except Exception as error:
            _executions.append({"executor": "e2b", "ok": False, "detail": str(error)[:200]})
    return _run_locally(source, values), "local"


def issues_fingerprint(issues: list[CleanerIssue]) -> tuple[str, ...]:
    """Identifies a failure set, so a repair loop can tell a new failure from the same one again."""
    return tuple(sorted(f"{issue.category}:{issue.input_value}" for issue in issues))


def close_sandbox() -> None:
    """Releases the sandbox held open across a run. A caller that opens one owns closing it: the
    handle survives the call that created it, so in a long-lived process such as the Streamlit
    gate an unclosed sandbox stays billed and connected for the whole session."""
    global _sandbox
    if _sandbox is not None:
        try:
            _sandbox.kill()
        finally:
            _sandbox = None


def start_execution_log() -> None:
    """Begins recording which executor ran each generated cleaner, for the run about to start."""
    _executions.clear()


def execution_log() -> list[dict]:
    """What ran where, so the report can state whether the sandbox or the local cage validated
    each function rather than leaving the reader to assume."""
    return list(_executions)


def _check_shape(tree: ast.Module) -> list[CleanerIssue]:
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    if len(tree.body) != len(functions) or len(functions) != 1:
        return [CleanerIssue(
            category="malformed_source",
            message="the source must contain exactly one function definition and nothing else.",
            expected_behavior=f"define {FUNCTION_NAME}(value) and no module-level statements.",
        )]
    function = functions[0]
    if function.name != FUNCTION_NAME:
        return [CleanerIssue(
            category="malformed_source",
            message=f"the function is named {function.name!r}, expected {FUNCTION_NAME!r}.",
            expected_behavior=f"name the function {FUNCTION_NAME!r}.",
        )]
    arguments = function.args
    positional = arguments.posonlyargs + arguments.args
    if len(positional) != 1 or arguments.vararg or arguments.kwarg or arguments.kwonlyargs:
        return [CleanerIssue(
            category="malformed_source",
            message=f"{FUNCTION_NAME} must take exactly one positional parameter.",
            expected_behavior=f"define {FUNCTION_NAME}(value).",
        )]
    return []


def _check_constructs(tree: ast.Module) -> list[CleanerIssue]:
    issues: list[CleanerIssue] = []
    for node in ast.walk(tree):
        issues.extend(_check_node(node))
    return issues


def _check_node(node: ast.AST) -> list[CleanerIssue]:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return _check_import(node)
    if isinstance(node, ast.While):
        return [_forbidden(
            "while loops are not available to a generated cleaner",
            "normalise a scalar with bounded control flow; iterate over a finite sequence.",
        )]
    if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
        return [_forbidden(
            f"attribute {node.attr!r} reaches into the interpreter internals",
            "use the value's ordinary methods only.",
        )]
    if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
        return [_forbidden(
            f"{node.id!r} is not available to a generated cleaner",
            "transform the value with plain expressions and the allowed modules.",
        )]
    return []


def _check_import(node: ast.Import | ast.ImportFrom) -> list[CleanerIssue]:
    if isinstance(node, ast.ImportFrom):
        modules = [node.module or ""]
    else:
        modules = [alias.name for alias in node.names]
    forbidden = [name for name in modules if name.split(".")[0] not in _ALLOWED_MODULES]
    if not forbidden:
        return []
    return [_forbidden(
        f"module {forbidden[0]!r} is not available to a generated cleaner",
        f"import only from {sorted(_ALLOWED_MODULES)}.",
    )]


def _forbidden(message: str, expected: str) -> CleanerIssue:
    return CleanerIssue(
        category="forbidden_construct", message=message, expected_behavior=expected
    )


def _restricted_builtins() -> dict[str, Any]:
    import builtins

    allowed = {name: getattr(builtins, name) for name in _SAFE_BUILTIN_NAMES}
    allowed["__import__"] = _guarded_import
    allowed["None"] = None
    allowed["True"] = True
    allowed["False"] = False
    return allowed


def _guarded_import(name: str, *args, **kwargs):
    if name.split(".")[0] not in _ALLOWED_MODULES:
        raise ImportError(f"module {name!r} is not available to a generated cleaner")
    return __import__(name, *args, **kwargs)


def _run_locally(source: str, values: list[str | None]) -> list[dict]:
    cleaner = load_callable(source)
    results: list[dict] = []
    for value in values:
        try:
            cleaned = cleaner(value)
        except Exception as error:
            results.append({"ok": False, "error": f"{type(error).__name__}: {error}"})
            continue
        results.append({"ok": True, "value": None if cleaned is None else str(cleaned)})
    return results


_sandbox = None
_executions: list[dict] = []


def _run_in_sandbox(source: str, values: list[str | None]) -> list[dict]:
    execution = _sandbox_handle().run_code(
        _driver_script(source, values), timeout=_SANDBOX_TIMEOUT_SECONDS
    )
    if execution.error is not None:
        raise RuntimeError(f"{execution.error.name}: {execution.error.value}")
    for line in reversed(execution.logs.stdout):
        if _SANDBOX_MARKER in line:
            return json.loads(line.split(_SANDBOX_MARKER, 1)[1])
    raise RuntimeError("the sandbox produced no cleaner results")


def _sandbox_handle():
    global _sandbox
    if _sandbox is None:
        from e2b_code_interpreter import Sandbox

        _sandbox = Sandbox.create()
    return _sandbox


def _driver_script(source: str, values: list[str | None]) -> str:
    return (
        "import json\n"
        f"{source}\n"
        f"_values = json.loads({json.dumps(json.dumps(values))})\n"
        "_results = []\n"
        "for _value in _values:\n"
        "    try:\n"
        f"        _cleaned = {FUNCTION_NAME}(_value)\n"
        "    except Exception as _error:\n"
        "        _results.append({'ok': False, 'error': type(_error).__name__ + ': ' + str(_error)})\n"
        "        continue\n"
        "    _results.append({'ok': True, 'value': None if _cleaned is None else str(_cleaned)})\n"
        f"print({json.dumps(_SANDBOX_MARKER)} + json.dumps(_results))\n"
    )


def _judge(
    values: list[str | None], results: list[dict], expected_unchanged: bool, dtype: str
) -> list[CleanerIssue]:
    issues: list[CleanerIssue] = []
    for value, result in zip(values, results):
        if not result.get("ok"):
            issues.append(CleanerIssue(
                category="runtime_exception",
                message=f"the cleaner raised on {value!r}: {result.get('error', '')}",
                input_value=value,
                expected_behavior="return a value or None for every input, never raise.",
            ))
            continue
        cleaned = result.get("value")
        if expected_unchanged:
            issues.extend(_judge_dominant(value, cleaned))
            continue
        issues.extend(_judge_inconsistent(value, cleaned, dtype))
    return issues


def _judge_dominant(value: str | None, cleaned: str | None) -> list[CleanerIssue]:
    if cleaned == value:
        return []
    return [CleanerIssue(
        category="dominant_value_modified",
        message=f"{value!r} already conforms but the cleaner returned {cleaned!r}.",
        input_value=value,
        actual_output=cleaned,
        expected_behavior="return an already valid value unchanged.",
    )]


def _judge_inconsistent(value: str | None, cleaned: str | None, dtype: str) -> list[CleanerIssue]:
    if cleaned == value:
        return [CleanerIssue(
            category="outlier_unchanged",
            message=f"{value!r} violates the column format but was returned unchanged.",
            input_value=value,
            actual_output=cleaned,
            expected_behavior="normalise the value, or return None when it is unrecoverable.",
        )]
    if cleaned is None or is_parseable(cleaned, dtype):
        return []
    return [CleanerIssue(
        category="not_parseable_as_target_dtype",
        message=f"{value!r} became {cleaned!r}, which is not readable as {dtype}.",
        input_value=value,
        actual_output=cleaned,
        expected_behavior=f"produce a value parseable as {dtype}.",
    )]


def is_parseable(value: str, dtype: str) -> bool:
    """Whether a cleaned value survives the cast the column is headed for."""
    if dtype.startswith("datetime"):
        return bool(pd.notna(pd.to_datetime(value, errors="coerce")))
    if dtype.lower().startswith(("int", "float")):
        return bool(pd.notna(pd.to_numeric(value, errors="coerce")))
    return True


def _as_scalar(value: Any) -> str | None:
    if value is None or (not isinstance(value, (list, dict, set)) and pd.isna(value)):
        return None
    return str(value)
