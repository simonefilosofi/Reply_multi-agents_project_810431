"""Stateless utilities for CodeValidatorAgent (Layer 3.5).

After Step 12 the primary sandbox is a Docker container running the embedded
``_RUNNER_SCRIPT`` with a restricted ``__builtins__`` whitelist and the
defence options listed in the plan: ``network_mode='none'``, ``read_only``
rootfs, all caps dropped, ``mem_limit`` / ``memswap_limit`` /
``cpu_quota`` / ``pids_limit``, tmpfs at /tmp, and the ``nobody``
(65534:65534) UID. ``run_in_subprocess_fallback`` runs the same runner in
an isolated Python subprocess with ``resource.setrlimit`` for CPU and
address-space on POSIX hosts; on Windows the rlimit calls are silently
skipped and the AST guard plus restricted builtins remain the only
defences. ``run_sandboxed`` is the dispatcher: it probes Docker once per
process via ``client.ping()`` and degrades to the fallback with a single
warning when Docker is unreachable. The Step 6 filter helpers, prompt
builders, and post-fix safety guards are preserved unchanged.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import socket
import subprocess
import sys

import numpy as np
import pandas as pd

from state.config import Settings
from state.helpers import non_empty_values

logger = logging.getLogger(__name__)

CHANGE_THRESHOLD = 0.20
TYPE_DRIFT_THRESHOLD = 0.10
SANDBOX_TIMEOUT = 10


_RUNNER_SCRIPT = """
import sys
import json
import io
import pandas as pd
import numpy as np
import re
import math

ALLOWED_BUILTINS = {
    "len": len, "range": range, "enumerate": enumerate, "print": print,
    "min": min, "max": max, "sum": sum, "abs": abs,
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "dict": dict, "set": set, "tuple": tuple,
    "isinstance": isinstance,
    "Exception": Exception, "ValueError": ValueError,
    "TypeError": TypeError, "KeyError": KeyError,
}

payload = json.loads(sys.stdin.read())
df = pd.read_csv(io.StringIO(payload["csv"]), dtype=str, keep_default_na=False)
col = payload["col"]
code = payload["code"]
namespace = {
    "__builtins__": ALLOWED_BUILTINS,
    "pd": pd, "np": np, "re": re, "math": math,
}

_user_stdout = io.StringIO()
_real_stdout = sys.stdout
sys.stdout = _user_stdout
try:
    exec(code, namespace)
    if "fix" not in namespace or not callable(namespace["fix"]):
        response = {"ok": False, "error": "no callable fix() defined"}
    else:
        namespace["fix"](df, col)
        response = {"ok": True, "csv": df.to_csv(index=False)}
except Exception as e:
    response = {"ok": False, "error": f"{type(e).__name__}: {e}"}
finally:
    sys.stdout = _real_stdout

print(json.dumps(response))
""".strip()


_FALLBACK_PREAMBLE = """
try:
    import resource as _resource
    _resource.setrlimit(_resource.RLIMIT_CPU, ({timeout_s}, {timeout_s}))
    _resource.setrlimit(_resource.RLIMIT_AS, ({mem_bytes}, {mem_bytes}))
    del _resource
except (ImportError, ValueError, OSError):
    pass

import os as _os
_os.environ.clear()
del _os
""".strip()


def _parse_mem_to_bytes(mem_limit: str) -> int:
    s = mem_limit.strip().lower().rstrip("b").rstrip()
    units = {"g": 1024**3, "m": 1024**2, "k": 1024}
    if s and s[-1] in units:
        return int(s[:-1]) * units[s[-1]]
    return int(s)


_DOCKER_AVAILABLE: bool | None = None
_FALLBACK_WARNED = False


def _is_docker_available() -> bool:
    global _DOCKER_AVAILABLE
    if _DOCKER_AVAILABLE is not None:
        return _DOCKER_AVAILABLE
    try:
        import docker

        client = docker.from_env()
        client.ping()
        _DOCKER_AVAILABLE = True
    except Exception:
        _DOCKER_AVAILABLE = False
    return _DOCKER_AVAILABLE


def _reset_docker_probe() -> None:
    """Test-only reset of the memoised Docker probe and fallback warning."""
    global _DOCKER_AVAILABLE, _FALLBACK_WARNED
    _DOCKER_AVAILABLE = None
    _FALLBACK_WARNED = False


def _maybe_warn_fallback() -> None:
    global _FALLBACK_WARNED
    if _FALLBACK_WARNED:
        return
    if sys.platform == "win32":
        logger.warning(
            "Docker unavailable; CodeValidator using subprocess fallback "
            "(no rlimit on Windows -- AST guard + restricted builtins only)"
        )
    else:
        logger.warning(
            "Docker unavailable; CodeValidator using subprocess fallback "
            "with RLIMIT_CPU and RLIMIT_AS"
        )
    _FALLBACK_WARNED = True


def _parse_runner_output(stdout: str) -> tuple[bool, pd.DataFrame | str]:
    cleaned = stdout.strip()
    if not cleaned:
        return False, "empty sandbox output"
    last_line = cleaned.splitlines()[-1]
    try:
        response = json.loads(last_line)
    except json.JSONDecodeError as exc:
        return False, f"unparseable sandbox output: {exc}"
    if response.get("ok"):
        return True, pd.read_csv(io.StringIO(response["csv"]), dtype=str, keep_default_na=False)
    return False, str(response.get("error", "fix failed"))


def run_in_docker(
    df: pd.DataFrame,
    col: str,
    code: str,
    settings: Settings,
) -> tuple[bool, pd.DataFrame | str]:
    """Run a fix function inside an isolated Docker container."""
    import docker

    container = None
    try:
        client = docker.from_env()
        payload = {"csv": df.to_csv(index=False), "code": code, "col": col}
        container = client.containers.run(
            image=settings.code_validator.docker_image,
            command=["python", "-c", _RUNNER_SCRIPT],
            stdin_open=True,
            detach=True,
            network_mode="none",
            read_only=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            mem_limit=settings.code_validator.docker_mem_limit,
            memswap_limit=settings.code_validator.docker_mem_limit,
            cpu_quota=settings.code_validator.docker_cpu_quota,
            pids_limit=64,
            tmpfs={"/tmp": "size=64m,mode=1777"},
            user="65534:65534",
        )
        sock = container.attach_socket(params={"stdin": 1, "stream": 1})
        try:
            sock._sock.sendall(json.dumps(payload).encode() + b"\n")
            sock._sock.shutdown(socket.SHUT_WR)
        finally:
            sock.close()
        result = container.wait(timeout=settings.code_validator.sandbox_timeout_s)
        stdout = container.logs(stdout=True, stderr=False).decode()
        stderr = container.logs(stdout=False, stderr=True).decode()
        if result.get("StatusCode", 1) != 0:
            return False, stderr.strip() or "non-zero container exit"
        return _parse_runner_output(stdout)
    except docker.errors.ContainerError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        if container is not None:
            with contextlib.suppress(Exception):
                container.remove(force=True)


def run_in_subprocess_fallback(
    df: pd.DataFrame,
    col: str,
    code: str,
    settings: Settings,
) -> tuple[bool, pd.DataFrame | str]:
    """Run the same runner script in an isolated Python subprocess.

    On POSIX hosts this enforces RLIMIT_CPU and RLIMIT_AS via
    ``resource.setrlimit``; on Windows the rlimit calls are skipped and the
    AST guard plus restricted ``__builtins__`` whitelist remain the only
    defences.
    """
    timeout_s = settings.code_validator.sandbox_timeout_s
    mem_bytes = _parse_mem_to_bytes(settings.code_validator.docker_mem_limit)
    full_script = (
        _FALLBACK_PREAMBLE.format(timeout_s=timeout_s, mem_bytes=mem_bytes) + "\n" + _RUNNER_SCRIPT
    )
    payload = {"csv": df.to_csv(index=False), "code": code, "col": col}
    try:
        proc = subprocess.run(
            [sys.executable, "-c", full_script],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return False, f"Subprocess timed out after {timeout_s}s"
    if proc.returncode != 0:
        return False, proc.stderr.decode().strip() or "non-zero subprocess exit"
    return _parse_runner_output(proc.stdout.decode())


def run_sandboxed(
    df: pd.DataFrame,
    col: str,
    code: str,
    settings: Settings,
) -> tuple[bool, pd.DataFrame | str]:
    """Dispatch sandboxed execution to Docker primary, subprocess fallback."""
    if _is_docker_available():
        return run_in_docker(df, col, code, settings)
    _maybe_warn_fallback()
    return run_in_subprocess_fallback(df, col, code, settings)


# ── Filter helpers ─────────────────────────────────────────────────────────────


def eval_filter_expression(
    filter_expr: str,
    df: pd.DataFrame,
    col: str,
) -> tuple[pd.Series | None, str]:
    """Evaluate a filter expression string against df[col].

    Returns (mask, error). mask is a boolean Series on success; error is a
    non-empty string describing the failure on error.
    """
    try:
        mask = eval(
            filter_expr,
            {"df": df, "col": col, "pd": pd, "np": np},
        )
        if isinstance(mask, pd.Series):
            mask = mask.reindex(df.index, fill_value=False)
        else:
            mask = pd.Series(mask, index=df.index)
        return mask.fillna(False).astype(bool), ""
    except Exception as e:
        return None, str(e)


def check_filter_coverage(
    target: pd.DataFrame,
    df: pd.DataFrame,
    filter_expr: str,
    col: str | None = None,
) -> str:
    """Return a non-empty feedback string if the filter is invalid, else ''.

    Only fails on 0 rows selected (expression too strict or values already fixed).
    """
    if len(target) == 0:
        sample_col = col if col and col in df.columns else df.columns[0]
        sample = list(non_empty_values(df[sample_col]).head(10).astype(str))
        return (
            f"The expression '{filter_expr}' matched 0 rows. "
            f"Either the condition is too strict or the values look different "
            f"from what you expected. "
            f"Sample of actual column values: {sample}. "
            f"Write a broader or corrected expression."
        )
    return ""


# ── Subsample builder ──────────────────────────────────────────────────────────


def build_test_subsample(
    df: pd.DataFrame,
    target_rows: pd.DataFrame,
    n_normal: int = 50,
) -> pd.DataFrame:
    """Build a mixed test subsample: all target rows + up to n_normal random rows.

    Normal rows are drawn from df excluding target_rows indices so that the
    subsample exercises both the fix logic (target) and regression safety
    (normal values that should remain unchanged).
    """
    normal_pool = df[~df.index.isin(target_rows.index)]
    normal_rows = (
        normal_pool.sample(min(n_normal, len(normal_pool)), random_state=42)
        if len(normal_pool) > 0
        else normal_pool
    )
    return pd.concat([target_rows, normal_rows]).drop_duplicates().reset_index(drop=True)


# ── Safety guards ──────────────────────────────────────────────────────────────


def safety_guard_quantitative(
    original: pd.Series,
    fixed: pd.Series,
    issue_type: str = "",
) -> tuple[bool, str]:
    """Fail if more than CHANGE_THRESHOLD of values were changed.

    Normalisation issues (case, format) are expected to touch many rows,
    so a relaxed threshold of 1.0 (no limit) is used for those types.
    """
    normalisation_types = {"case_inconsistency", "format_issue", "format_inconsistency"}
    threshold = 1.0 if issue_type in normalisation_types else CHANGE_THRESHOLD
    pct_changed = (fixed.values != original.values).mean()
    if pct_changed > threshold:
        return False, (f"Too many values changed: {pct_changed:.0%} > {threshold:.0%} threshold")
    return True, ""


def safety_guard_type_consistency(
    original: pd.Series,
    fixed: pd.Series,
) -> tuple[bool, str]:
    """Fail if the numeric-parseable rate shifts by more than TYPE_DRIFT_THRESHOLD."""
    orig_rate = pd.to_numeric(original, errors="coerce").notna().mean()
    fixed_rate = pd.to_numeric(fixed, errors="coerce").notna().mean()
    delta = abs(orig_rate - fixed_rate)
    if delta > TYPE_DRIFT_THRESHOLD:
        return False, (
            f"Numeric type distribution shifted: "
            f"{orig_rate:.2f} → {fixed_rate:.2f} "
            f"(delta {delta:.2f} > {TYPE_DRIFT_THRESHOLD})"
        )
    return True, ""


# ── Prompt builders ────────────────────────────────────────────────────────────


def build_filter_prompt(
    col: str,
    issue: dict,
    df: pd.DataFrame,
    feedback: str = "",
) -> str:
    """Build the LLM prompt for generating a filter expression."""
    dtype = str(df[col].dtype)
    sample = list(non_empty_values(df[col]).head(20).astype(str))
    feedback_line = f"\nPrevious attempt feedback: {feedback}" if feedback else ""
    dtype_hint = (
        "IMPORTANT: df[col] is NOT object/string dtype — use "
        f".astype(str) before any .str accessor (dtype={dtype}).\n"
        if dtype not in ("object", "string")
        else ""
    )
    return (
        f"Column: '{col}' (dtype: {dtype})\n"
        f"Issue: {issue['detail']}\n"
        f"Sample values: {sample}{feedback_line}\n\n"
        f"{dtype_hint}"
        "Write a single Python boolean expression using df[col] that "
        "selects exactly the rows containing this issue. "
        "The expression must evaluate to a pandas boolean Series. "
        "Use only pandas/numpy operations on df[col].\n"
        "Examples:\n"
        "  df[col] == '-999'\n"
        "  df[col].astype(str).str.contains(r'[€$£]', regex=True, na=False)\n"
        "  pd.to_numeric(df[col], errors='coerce').lt(0)\n"
        'Return JSON: {"filter": "...", "explanation": "..."}'
    )


def build_fix_prompt(
    issue: dict,
    target_rows: pd.DataFrame,
    previous_code: str = "",
    previous_error: str = "",
) -> str:
    """Build the LLM prompt for generating (or rewriting) a fix function."""
    col = issue["column"]
    dtype = str(target_rows[col].dtype)
    target_sample = list(target_rows[col].head(20).astype(str))
    dtype_hint = (
        f"IMPORTANT: df[col] has dtype={dtype} (not object). "
        "Always call df[col].astype(str) before using .str methods.\n\n"
        if dtype not in ("object", "string")
        else ""
    )

    if previous_error:
        return (
            f"The following Python function produced an error:\n\n"
            f"{previous_code}\n\n"
            f"Error: {previous_error}\n"
            f"Column dtype: {dtype}\n"
            f"Sample of problematic values: {target_sample}\n\n"
            f"{dtype_hint}"
            f"Rewrite the function to fix this error. "
            f"Keep the same fix logic — only add handling for the error case. "
            f"Return only the corrected function code, no explanation."
        )
    return (
        f"Column: '{col}' (dtype: {dtype})\n"
        f"Issue: {issue['detail']}\n"
        f"Sample values to fix: {target_sample}\n\n"
        f"{dtype_hint}"
        f"Write a Python function named 'fix(df, col)' that corrects "
        f"this issue in df[col] in-place. "
        f"Use only pandas and numpy. "
        f"Return only the function code, no explanation."
    )


def build_llm_review_prompt(
    issue: dict,
    original: pd.Series,
    fixed: pd.Series,
) -> str:
    """Build the LLM safety-review prompt comparing original vs fixed values."""
    orig_sample = list(original.dropna().head(10).astype(str))
    fixed_sample = list(fixed.dropna().head(10).astype(str))
    return (
        f"Issue being fixed: {issue['detail']}\n"
        f"Original values (sample): {orig_sample}\n"
        f"Fixed values (sample):    {fixed_sample}\n\n"
        "Does the fix correctly address the issue without introducing "
        "new problems? "
        'Return JSON: {"approved": true/false, "reason": "..."}'
    )


# ── Code extraction ────────────────────────────────────────────────────────────


def extract_code_from_llm_response(raw: str) -> str:
    """Strip markdown code fences from an LLM response, returning bare code."""
    raw = raw.strip()
    if "```python" in raw:
        return raw.split("```python")[1].split("```")[0].strip()
    if "```" in raw:
        return raw.split("```")[1].split("```")[0].strip()
    return raw
