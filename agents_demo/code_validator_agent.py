"""Layer 3.5 — CodeValidatorAgent.

Receives gap issues (source='synthesis_gap_detection') that have no
deterministic handler in RemediationAgent, generates a Python fix function
via LLM, validates it with AST inspection + subprocess sandbox, and applies
it to the DataFrame through a self-healing retry loop (max 3 attempts).

If after MAX_RETRIES the fix still fails, the issue is appended to
state.human_review_items for manual inspection.
"""

import os
import subprocess
import sys
import tempfile

import pandas as pd

from agents_demo.base_agent import BaseAgent, SMART
from state_demo.helpers import non_empty_values
from tools import validate_generated_code

MAX_RETRIES = 3
CHANGE_THRESHOLD = 0.20       # safety guard: max fraction of column changed
TYPE_DRIFT_THRESHOLD = 0.10   # safety guard: max numeric-rate shift allowed
FILTER_COVERAGE_LIMIT = 0.50  # reject filters that select >50% of rows
SANDBOX_TIMEOUT = 10          # seconds


class CodeValidatorAgent(BaseAgent):
    name = "code_validator"
    model = SMART

    INSTRUCTION = (
        "You are a Python data-cleaning code generator. "
        "You write simple, safe pandas functions to fix specific data quality issues. "
        "Functions must be named 'fix', accept (df, col) as arguments, "
        "modify df[col] in-place, and return nothing. "
        "Use only pandas and numpy. Never import os, sys, subprocess, or any "
        "module not in {pandas, numpy, re, math}."
    )

    # ── Public entry point ────────────────────────────────────────────────────

    def run(self, gap_issues: list) -> None:
        self._gap_issues = gap_issues
        self.prompt = f"Fix {len(gap_issues)} gap issues via LLM-generated code"
        self.think()
        self.act()
        self.observe()
        self.reply()

    # ── TAOR protocol ─────────────────────────────────────────────────────────

    def think(self):
        self.log("think",
                 f"{self.prompt} | max {MAX_RETRIES} retries per issue, "
                 f"sandbox timeout {SANDBOX_TIMEOUT}s")

    def act(self):
        df = (self.state.df_cleaned
              if self.state.df_cleaned is not None
              else self.state.df_raw.copy())

        for issue in self._gap_issues:
            col = issue.get("column")
            if not col or col not in df.columns:
                self.log("act", f"Skipping gap issue — column '{col}' not in DataFrame")
                continue
            self.log("act",
                     f"Processing gap issue on '{col}': {issue.get('type')}")
            self._process_issue(df, issue)

        self.state.df_cleaned = df

    def observe(self):
        applied = sum(
            1 for f in self.state.fix_log
            if f.get("action") == "auto_fixed_by_llm"
        )
        flagged = len(self.state.human_review_items)
        self.log("observe",
                 f"CodeValidator complete — {applied} LLM fixes applied, "
                 f"{flagged} item(s) flagged for human review")

    def reply(self):
        pass

    # ── Core processing loop ──────────────────────────────────────────────────

    def _process_issue(self, df: pd.DataFrame, issue: dict):
        col = issue["column"]

        # Step 1 — validate filter and obtain target rows
        target_rows, skip_reason = self._validate_filter(df, col, issue)
        if skip_reason:
            self._add_human_review(issue, "", skip_reason, 0, skip_reason)
            return

        last_code = ""
        last_error = ""

        for attempt in range(1, MAX_RETRIES + 1):
            self.log("act", f"'{col}' — attempt {attempt}/{MAX_RETRIES}")

            # Step 2 — generate (or regenerate) fix function
            last_code = self._generate_fix(issue, target_rows,
                                           last_code, last_error)
            if not last_code:
                last_error = "LLM returned empty code"
                continue

            # Step 3 — AST validation
            valid, reason = validate_generated_code(last_code)
            if not valid:
                last_error = f"AST validation failed: {reason}"
                self.log("act", last_error)
                continue

            # Step 4 — build mixed subsample (target rows + random normal rows)
            normal_pool = df[~df.index.isin(target_rows.index)]
            normal_rows = (
                normal_pool.sample(min(50, len(normal_pool)), random_state=42)
                if len(normal_pool) > 0
                else normal_pool
            )
            test_sample = (
                pd.concat([target_rows, normal_rows])
                .drop_duplicates()
                .reset_index(drop=True)
            )

            # Step 5 — run in subprocess sandbox
            success, result_or_error = self._run_in_sandbox(
                test_sample, col, last_code
            )
            if not success:
                last_error = result_or_error
                self.log("act",
                         f"Sandbox error on attempt {attempt}: {last_error}")
                continue

            # Step 6 — safety guards on subsample result
            passed, guard_reason = self._safety_guards(
                test_sample[col], result_or_error[col], issue
            )
            if not passed:
                last_error = f"Safety guard failed: {guard_reason}"
                self.log("act", last_error)
                continue

            # Step 7 — all checks passed: apply to full DataFrame
            original_col = df[col].copy()
            success_full, result_full_or_error = self._run_in_sandbox(
                df, col, last_code
            )
            if success_full:
                fixed_col = result_full_or_error[col].values
                rows_affected = int(
                    (fixed_col != original_col.values).sum()
                )
                df[col] = fixed_col
                self.log("act",
                         f"Fix applied to '{col}' on attempt {attempt} "
                         f"({rows_affected} rows changed)")
                self.state.fix_log.append({
                    "issue_type": issue["type"],
                    "column": col,
                    "action": "auto_fixed_by_llm",
                    "description": issue.get("detail", ""),
                    "rows_affected": rows_affected,
                    "attempts": attempt,
                    "generated_code": last_code,
                })
                return
            else:
                last_error = result_full_or_error

        # Exhausted retries
        self._add_human_review(
            issue, last_code, last_error, MAX_RETRIES, "max_retries_exceeded"
        )

    # ── Filter validation ─────────────────────────────────────────────────────

    def _validate_filter(
        self, df: pd.DataFrame, col: str, issue: dict
    ) -> tuple[pd.DataFrame, str]:
        """Try up to MAX_RETRIES times to produce a valid filter expression.

        On each failure the reason (eval error, 0 rows, too broad) is passed
        back to the LLM so it can refine the expression.
        """
        import numpy as np

        filter_expr = issue.get("filter", "").strip()
        last_feedback = ""

        for attempt in range(1, MAX_RETRIES + 1):
            self.log("act",
                     f"Filter attempt {attempt}/{MAX_RETRIES} for '{col}'")

            # (Re)generate filter if missing or previous attempt failed
            if not filter_expr:
                filter_expr = self._generate_filter(
                    df, col, issue, feedback=last_feedback
                )
            if not filter_expr:
                last_feedback = "LLM returned an empty filter expression"
                filter_expr = ""
                continue

            # Evaluate the expression
            try:
                mask = eval(  # noqa: S307
                    filter_expr,
                    {"df": df, "col": col, "pd": pd, "np": np},
                )
                if not isinstance(mask, pd.Series):
                    mask = pd.Series(mask, index=df.index)
                mask = mask.fillna(False).astype(bool)
                target = df[mask]
            except Exception as e:
                last_feedback = (
                    f"The expression raised a Python error: {e}. "
                    f"Rewrite it so it evaluates without exceptions."
                )
                self.log("act", f"Filter eval error: {e}")
                filter_expr = ""
                continue

            # Check: 0 rows found
            if len(target) == 0:
                last_feedback = (
                    f"The expression '{filter_expr}' is syntactically valid "
                    f"but matched 0 rows. "
                    f"Either the condition is too strict or the values look "
                    f"different from what you expected. "
                    f"Sample of actual values in the column: "
                    f"{list(non_empty_values(df[col]).head(10).astype(str))}. "
                    f"Write a broader or corrected expression."
                )
                self.log("act", f"Filter found 0 rows — retrying")
                filter_expr = ""
                continue

            # Check: filter too broad
            coverage = len(target) / len(df)
            if coverage > FILTER_COVERAGE_LIMIT:
                last_feedback = (
                    f"The expression '{filter_expr}' matched {coverage:.0%} of "
                    f"all rows — too broad. "
                    f"It must select only the rows that contain the specific "
                    f"problem, not the majority of the dataset. "
                    f"Make the condition more precise."
                )
                self.log("act",
                         f"Filter too broad ({coverage:.0%}) — retrying")
                filter_expr = ""
                continue

            # Valid filter found
            self.log("act",
                     f"Filter valid — {len(target)} target rows "
                     f"({coverage:.1%} of dataset)")
            return target, ""

        # All attempts exhausted
        return (
            pd.DataFrame(),
            f"filter_failed_after_{MAX_RETRIES}_attempts: {last_feedback}",
        )

    def _generate_filter(
        self,
        df: pd.DataFrame,
        col: str,
        issue: dict,
        feedback: str = "",
    ) -> str:
        sample = list(non_empty_values(df[col]).head(20).astype(str))
        feedback_line = (
            f"\nPrevious attempt feedback: {feedback}" if feedback else ""
        )
        user = (
            f"Column: '{col}'\n"
            f"Issue: {issue['detail']}\n"
            f"Sample values: {sample}{feedback_line}\n\n"
            "Write a single Python boolean expression using df[col] that "
            "selects exactly the rows containing this issue. "
            "The expression must evaluate to a pandas boolean Series. "
            "Use only pandas/numpy operations on df[col]. "
            "Examples:\n"
            "  df[col] == '-999'\n"
            "  df[col].str.contains(r'[€$£]', regex=True, na=False)\n"
            "  pd.to_numeric(df[col], errors='coerce').lt(0)\n"
            'Return JSON: {"filter": "...", "explanation": "..."}'
        )
        try:
            result = self.call_llm_json(user, max_tokens=256)
            return result.get("filter", "").strip()
        except Exception as e:
            self.log("act", f"Filter generation failed: {e}")
            return ""

    # ── Code generation ───────────────────────────────────────────────────────

    def _generate_fix(
        self,
        issue: dict,
        target_rows: pd.DataFrame,
        previous_code: str,
        previous_error: str,
    ) -> str:
        col = issue["column"]
        target_sample = list(target_rows[col].head(20).astype(str))

        if previous_error:
            prompt = (
                f"The following Python function produced an error:\n\n"
                f"{previous_code}\n\n"
                f"Error: {previous_error}\n"
                f"Sample of problematic values: {target_sample}\n\n"
                f"Rewrite the function to fix this error. "
                f"Keep the same fix logic — only add handling for the error case. "
                f"Return only the corrected function code, no explanation."
            )
        else:
            prompt = (
                f"Column: '{col}'\n"
                f"Issue: {issue['detail']}\n"
                f"Sample values to fix: {target_sample}\n\n"
                f"Write a Python function named 'fix(df, col)' that corrects "
                f"this issue in df[col] in-place. "
                f"Use only pandas and numpy. "
                f"Return only the function code, no explanation."
            )

        try:
            raw = self.call_llm(prompt, max_tokens=512).strip()
            if "```python" in raw:
                raw = raw.split("```python")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return raw.strip()
        except Exception as e:
            self.log("act", f"Code generation failed: {e}")
            return ""

    # ── Subprocess sandbox ────────────────────────────────────────────────────

    def _run_in_sandbox(
        self, df: pd.DataFrame, col: str, code: str
    ) -> tuple[bool, pd.DataFrame | str]:
        # Resolve sandbox_runner.py path relative to this file's project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        runner_path = os.path.join(project_root, "sandbox_runner.py")

        # Try to get sandbox_user uid; fall back to current user in dev
        sandbox_uid = None
        try:
            import pwd
            sandbox_uid = pwd.getpwnam("sandbox_user").pw_uid
        except (KeyError, ImportError):
            self.log("act",
                     "sandbox_user not found — running sandbox as current user")

        inp_path = func_path = out_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False
            ) as inp:
                inp_path = inp.name
            with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False
            ) as func:
                func_path = func.name
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False
            ) as out:
                out_path = out.name

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

            fixed_df = pd.read_csv(out_path, dtype=str)
            return True, fixed_df

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

    # ── Safety guards ─────────────────────────────────────────────────────────

    def _safety_guards(
        self,
        original: pd.Series,
        fixed: pd.Series,
        issue: dict,
    ) -> tuple[bool, str]:
        # Guard 1 — quantitative: too many values changed
        pct_changed = (fixed != original).mean()
        if pct_changed > CHANGE_THRESHOLD:
            return False, (
                f"Too many values changed: {pct_changed:.0%} > "
                f"{CHANGE_THRESHOLD:.0%} threshold"
            )

        # Guard 2 — type consistency: numeric rate must not shift significantly
        orig_num_rate = pd.to_numeric(original, errors="coerce").notna().mean()
        fixed_num_rate = pd.to_numeric(fixed,    errors="coerce").notna().mean()
        if abs(orig_num_rate - fixed_num_rate) > TYPE_DRIFT_THRESHOLD:
            return False, (
                f"Numeric type distribution shifted: "
                f"{orig_num_rate:.2f} → {fixed_num_rate:.2f} "
                f"(delta {abs(orig_num_rate - fixed_num_rate):.2f} > "
                f"{TYPE_DRIFT_THRESHOLD})"
            )

        # Guard 3 — LLM review of before/after sample
        orig_sample = list(original.dropna().head(10).astype(str))
        fixed_sample = list(fixed.dropna().head(10).astype(str))
        user = (
            f"Issue being fixed: {issue['detail']}\n"
            f"Original values (sample): {orig_sample}\n"
            f"Fixed values (sample):    {fixed_sample}\n\n"
            "Does the fix correctly address the issue without introducing "
            "new problems? "
            'Return JSON: {"approved": true/false, "reason": "..."}'
        )
        try:
            result = self.call_llm_json(user, max_tokens=256)
            if not result.get("approved", False):
                return False, (
                    f"LLM review rejected: {result.get('reason', 'no reason given')}"
                )
        except Exception as e:
            self.log("act", f"LLM safety review failed, proceeding: {e}")

        return True, "OK"

    # ── Human review logging ──────────────────────────────────────────────────

    def _add_human_review(
        self,
        issue: dict,
        code: str,
        error: str,
        attempts: int,
        reason: str,
    ):
        self.log(
            "act",
            f"'{issue['column']}' flagged for human review — {reason}",
        )
        self.state.human_review_items.append({
            "column": issue["column"],
            "issue": issue,
            "last_generated_code": code,
            "last_error": error,
            "attempts": attempts,
            "reason": reason,
        })
