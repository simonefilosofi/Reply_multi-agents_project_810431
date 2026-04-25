"""Layer 3.5 — CodeValidatorAgent.

Receives gap issues (source='synthesis_gap_detection') that have no
deterministic handler in RemediationAgent, generates a Python fix function
via LLM, validates it with AST inspection + subprocess sandbox, and applies
it to the DataFrame through a self-healing retry loop (max 3 attempts).

If after MAX_RETRIES the fix still fails, the issue is appended to
state.human_review_items for manual inspection.

All stateless utilities (sandbox, safety guards, prompt builders) live in
tools_code_validator.py; this file contains only agent coordination logic.
"""

import os
import re
import textwrap
from datetime import datetime

import pandas as pd

from agents_demo.base_agent import BaseAgent, SMART
from tools import validate_generated_code
from tools_code_validator import (
    SANDBOX_TIMEOUT,
    build_filter_prompt,
    build_fix_prompt,
    build_llm_review_prompt,
    build_test_subsample,
    check_filter_coverage,
    eval_filter_expression,
    extract_code_from_llm_response,
    resolve_sandbox_uid,
    run_in_sandbox,
    safety_guard_quantitative,
    safety_guard_type_consistency,
)

MAX_RETRIES = 3


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
                self.log("act",
                         f"Skipping gap issue — column '{col}' not in DataFrame")
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

        runner_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "sandbox_runner.py",
        )
        sandbox_uid = resolve_sandbox_uid()
        if sandbox_uid is None:
            self.log("act",
                     "sandbox_user not found — running sandbox as current user")

        last_code = ""
        last_error = ""

        for attempt in range(1, MAX_RETRIES + 1):
            self.log("act", f"'{col}' — attempt {attempt}/{MAX_RETRIES}")

            # Step 2 — generate (or regenerate) fix function
            last_code = self._call_fix_generation(
                issue, target_rows, last_code, last_error
            )
            if not last_code:
                last_error = "LLM returned empty code"
                continue

            # Step 3 — AST validation
            valid, reason = validate_generated_code(last_code)
            if not valid:
                last_error = f"AST validation failed: {reason}"
                self.log("act", last_error)
                continue

            # Step 4 — build mixed subsample (target + random normal rows)
            test_sample = build_test_subsample(df, target_rows)

            # Step 5 — run fix in subprocess sandbox
            success, result_or_error = run_in_sandbox(
                test_sample, col, last_code, runner_path, sandbox_uid
            )
            if not success:
                last_error = result_or_error
                self.log("act",
                         f"Sandbox error on attempt {attempt}: {last_error}")
                continue

            # Step 6 — safety guards on subsample result
            passed, guard_reason = self._run_safety_guards(
                test_sample[col], result_or_error[col], issue
            )
            if not passed:
                last_error = f"Safety guard failed: {guard_reason}"
                self.log("act", last_error)
                continue

            # Step 7 — apply to full DataFrame
            original_col = df[col].copy()
            success_full, result_full_or_error = run_in_sandbox(
                df, col, last_code, runner_path, sandbox_uid
            )
            if success_full:
                fixed_col = result_full_or_error[col].values
                rows_affected = int((fixed_col != original_col.values).sum())
                df[col] = fixed_col
                self.log("act",
                         f"Fix applied to '{col}' on attempt {attempt} "
                         f"({rows_affected} rows changed)")
                code_path = self._dump_code(
                    col, issue["type"], last_code, "applied", attempt
                )
                self.state.fix_log.append({
                    "issue_type": issue["type"],
                    "column": col,
                    "action": "auto_fixed_by_llm",
                    "description": issue.get("detail", ""),
                    "rows_affected": rows_affected,
                    "attempts": attempt,
                    "generated_code": last_code,
                    "code_file": code_path,
                })
                return
            else:
                last_error = result_full_or_error

        self._dump_code(
            col, issue["type"], last_code, "failed", MAX_RETRIES, error=last_error
        )
        self._add_human_review(
            issue, last_code, last_error, MAX_RETRIES, "max_retries_exceeded"
        )

    # ── Filter validation ─────────────────────────────────────────────────────

    def _validate_filter(
        self, df: pd.DataFrame, col: str, issue: dict
    ) -> tuple[pd.DataFrame, str]:
        filter_expr = issue.get("filter", "").strip()
        last_feedback = ""

        for attempt in range(1, MAX_RETRIES + 1):
            self.log("act",
                     f"Filter attempt {attempt}/{MAX_RETRIES} for '{col}'")

            if not filter_expr:
                filter_expr = self._call_filter_generation(
                    df, col, issue, last_feedback
                )
            if not filter_expr:
                last_feedback = "LLM returned an empty filter expression"
                filter_expr = ""
                continue

            mask, eval_error = eval_filter_expression(filter_expr, df, col)
            if eval_error:
                last_feedback = (
                    f"The expression raised a Python error: {eval_error}. "
                    f"Rewrite it so it evaluates without exceptions."
                )
                self.log("act", f"Filter eval error: {eval_error}")
                filter_expr = ""
                continue

            target = df[mask]
            coverage_feedback = check_filter_coverage(target, df, filter_expr, col)
            if coverage_feedback:
                last_feedback = coverage_feedback
                self.log("act",
                         f"Filter rejected ({len(target)} rows / "
                         f"{len(target)/len(df):.0%}) — retrying")
                filter_expr = ""
                continue

            self.log("act",
                     f"Filter valid — {len(target)} target rows "
                     f"({len(target)/len(df):.1%} of dataset)")
            return target, ""

        return (
            pd.DataFrame(),
            f"filter_failed_after_{MAX_RETRIES}_attempts: {last_feedback}",
        )

    # ── LLM call wrappers ─────────────────────────────────────────────────────

    def _call_filter_generation(
        self,
        df: pd.DataFrame,
        col: str,
        issue: dict,
        feedback: str,
    ) -> str:
        prompt = build_filter_prompt(col, issue, df, feedback)
        try:
            result = self.call_llm_json(prompt, max_tokens=256,
                                        required_keys=["filter"])
            return result.get("filter", "").strip()
        except Exception as e:
            self.log("act", f"Filter generation failed: {e}")
            return ""

    def _call_fix_generation(
        self,
        issue: dict,
        target_rows: pd.DataFrame,
        previous_code: str,
        previous_error: str,
    ) -> str:
        prompt = build_fix_prompt(issue, target_rows, previous_code, previous_error)
        try:
            raw = self.call_llm(prompt, max_tokens=512)
            return extract_code_from_llm_response(raw)
        except Exception as e:
            self.log("act", f"Code generation failed: {e}")
            return ""

    def _run_safety_guards(
        self,
        original: pd.Series,
        fixed: pd.Series,
        issue: dict,
    ) -> tuple[bool, str]:
        passed, reason = safety_guard_quantitative(original, fixed, issue.get("type", ""))
        if not passed:
            return False, reason

        passed, reason = safety_guard_type_consistency(original, fixed)
        if not passed:
            return False, reason

        prompt = build_llm_review_prompt(issue, original, fixed)
        try:
            result = self.call_llm_json(prompt, max_tokens=256,
                                        required_keys=["approved"])
            if not result.get("approved", False):
                return False, (
                    f"LLM review rejected: "
                    f"{result.get('reason', 'no reason given')}"
                )
        except Exception as e:
            self.log("act", f"LLM safety review failed, proceeding: {e}")

        return True, "OK"

    # ── Code persistence ──────────────────────────────────────────────────────

    _GENERATED_FIXES_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "generated_fixes",
    )

    def _dump_code(
        self,
        col: str,
        issue_type: str,
        code: str,
        status: str,
        attempt: int,
        error: str = "",
    ) -> str:
        """Write generated fix code to generated_fixes/<status>_<col>_<type>.py.

        Returns the file path written.
        """
        os.makedirs(self._GENERATED_FIXES_DIR, exist_ok=True)
        safe_col = re.sub(r"[^\w]", "_", col)
        safe_type = re.sub(r"[^\w]", "_", issue_type)
        ts = datetime.now().strftime("%H%M%S")
        filename = f"{status}__{safe_col}__{safe_type}__{ts}.py"
        path = os.path.join(self._GENERATED_FIXES_DIR, filename)

        header = textwrap.dedent(f"""\
            # Generated by CodeValidatorAgent
            # Column   : {col}
            # Issue    : {issue_type}
            # Status   : {status}
            # Attempt  : {attempt}
            # Timestamp: {datetime.now().isoformat(timespec='seconds')}
        """)
        if error:
            header += f"# Error    : {error}\n"
        header += "\n"

        with open(path, "w") as f:
            f.write(header + code)

        self.log("act", f"Code saved → generated_fixes/{filename}")
        return path

    # ── Human review logging ──────────────────────────────────────────────────

    def _add_human_review(
        self,
        issue: dict,
        code: str,
        error: str,
        attempts: int,
        reason: str,
    ):
        self.log("act",
                 f"'{issue['column']}' flagged for human review — {reason}")
        self.state.human_review_items.append({
            "column": issue["column"],
            "issue": issue,
            "last_generated_code": code,
            "last_error": error,
            "attempts": attempts,
            "reason": reason,
        })
