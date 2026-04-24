"""Stateless utility functions for CodeValidatorAgent.

All functions here are pure: they receive data in and return results out.
No LLM calls, no PipelineState access, no logging.
"""

import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from state_demo.helpers import non_empty_values

# ── Constants ──────────────────────────────────────────────────────────────────

CHANGE_THRESHOLD = 0.20
TYPE_DRIFT_THRESHOLD = 0.10
FILTER_COVERAGE_LIMIT = 0.50
SANDBOX_TIMEOUT = 10


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
        mask = eval(  # noqa: S307
            filter_expr,
            {"df": df, "col": col, "pd": pd, "np": np},
        )
        if not isinstance(mask, pd.Series):
            mask = pd.Series(mask, index=df.index)
        return mask.fillna(False).astype(bool), ""
    except Exception as e:
        return None, str(e)


def check_filter_coverage(
    target: pd.DataFrame,
    df: pd.DataFrame,
    filter_expr: str,
) -> str:
    """Return a non-empty feedback string if the filter is invalid, else ''.

    Checks two failure modes:
    - 0 rows selected (false positive / expression too strict)
    - >FILTER_COVERAGE_LIMIT rows selected (expression too broad)
    """
    if len(target) == 0:
        sample = list(non_empty_values(df[df.columns[0]]).head(10).astype(str))
        return (
            f"The expression '{filter_expr}' matched 0 rows. "
            f"Either the condition is too strict or the values look different "
            f"from what you expected. "
            f"Sample of actual column values: {sample}. "
            f"Write a broader or corrected expression."
        )
    coverage = len(target) / len(df)
    if coverage > FILTER_COVERAGE_LIMIT:
        return (
            f"The expression '{filter_expr}' matched {coverage:.0%} of all rows "
            f"— too broad. Select only the rows containing the specific problem, "
            f"not the majority of the dataset. Make the condition more precise."
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
    return (
        pd.concat([target_rows, normal_rows])
        .drop_duplicates()
        .reset_index(drop=True)
    )


# ── Subprocess sandbox ─────────────────────────────────────────────────────────

def run_in_sandbox(
    df: pd.DataFrame,
    col: str,
    code: str,
    runner_path: str,
    sandbox_uid: int | None = None,
) -> tuple[bool, pd.DataFrame | str]:
    """Run LLM-generated fix code in an isolated subprocess.

    Serialises df to a temp CSV, writes code to a temp .py file, invokes
    sandbox_runner.py as a child process (optionally as sandbox_user), and
    reads the result back from a temp output CSV.

    Returns (success, result_df) on success or (False, error_message) on any
    failure (non-zero exit code, timeout, unexpected exception).
    """
    inp_path = func_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            inp_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            func_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            out_path = f.name

        df.to_csv(inp_path, index=False)
        with open(func_path, "w") as f:
            f.write(code)

        run_kwargs: dict = dict(
            args=[sys.executable, runner_path,
                  inp_path, func_path, out_path, col],
            timeout=SANDBOX_TIMEOUT,
            capture_output=True,
        )
        if sandbox_uid is not None:
            run_kwargs["user"] = sandbox_uid

        proc = subprocess.run(**run_kwargs)

        if proc.returncode != 0:
            return False, proc.stderr.decode().strip()

        return True, pd.read_csv(out_path, dtype=str)

    except subprocess.TimeoutExpired:
        return False, f"Subprocess timed out after {SANDBOX_TIMEOUT}s"
    except Exception as e:
        return False, str(e)
    finally:
        for path in [inp_path, func_path, out_path]:
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass


def resolve_sandbox_uid() -> int | None:
    """Return the UID of sandbox_user, or None if not configured."""
    try:
        import pwd
        return pwd.getpwnam("sandbox_user").pw_uid
    except (KeyError, ImportError):
        return None


# ── Safety guards ──────────────────────────────────────────────────────────────

def safety_guard_quantitative(
    original: pd.Series,
    fixed: pd.Series,
) -> tuple[bool, str]:
    """Fail if more than CHANGE_THRESHOLD of values were changed."""
    pct_changed = (fixed != original).mean()
    if pct_changed > CHANGE_THRESHOLD:
        return False, (
            f"Too many values changed: {pct_changed:.0%} > "
            f"{CHANGE_THRESHOLD:.0%} threshold"
        )
    return True, ""


def safety_guard_type_consistency(
    original: pd.Series,
    fixed: pd.Series,
) -> tuple[bool, str]:
    """Fail if the numeric-parseable rate shifts by more than TYPE_DRIFT_THRESHOLD."""
    orig_rate = pd.to_numeric(original, errors="coerce").notna().mean()
    fixed_rate = pd.to_numeric(fixed,    errors="coerce").notna().mean()
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
    sample = list(non_empty_values(df[col]).head(20).astype(str))
    feedback_line = (
        f"\nPrevious attempt feedback: {feedback}" if feedback else ""
    )
    return (
        f"Column: '{col}'\n"
        f"Issue: {issue['detail']}\n"
        f"Sample values: {sample}{feedback_line}\n\n"
        "Write a single Python boolean expression using df[col] that "
        "selects exactly the rows containing this issue. "
        "The expression must evaluate to a pandas boolean Series. "
        "Use only pandas/numpy operations on df[col].\n"
        "Examples:\n"
        "  df[col] == '-999'\n"
        "  df[col].str.contains(r'[€$£]', regex=True, na=False)\n"
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
    target_sample = list(target_rows[col].head(20).astype(str))

    if previous_error:
        return (
            f"The following Python function produced an error:\n\n"
            f"{previous_code}\n\n"
            f"Error: {previous_error}\n"
            f"Sample of problematic values: {target_sample}\n\n"
            f"Rewrite the function to fix this error. "
            f"Keep the same fix logic — only add handling for the error case. "
            f"Return only the corrected function code, no explanation."
        )
    return (
        f"Column: '{col}'\n"
        f"Issue: {issue['detail']}\n"
        f"Sample values to fix: {target_sample}\n\n"
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
    orig_sample  = list(original.dropna().head(10).astype(str))
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
