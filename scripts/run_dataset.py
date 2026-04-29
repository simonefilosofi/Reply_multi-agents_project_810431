"""Live LLM run of the compiled pipeline on a single CSV.

Used as a manual exercise of the multi-agent pipeline against the real
NoiPA datasets shipped under ``Datasets-Reply-20260313/`` and against
the synthetic fixtures under ``data/examples/``. Prints reliability
score before/after, prioritized-issue counts by type, fix-log action
counts, and a short report excerpt so the LLM behaviour is visible.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import pandas as pd  # noqa: E402

from agents_demo._graph import build_pipeline_graph, state_from_dict  # noqa: E402
from agents_demo.report_agent import serialize_report  # noqa: E402
from state_demo import settings  # noqa: E402


def _install_lean_llm_patches() -> None:
    """Diagnostic monkey-patches that strip optional LLM calls.

    * ``enrich_with_llm`` returns the deterministic findings untouched
      (no Layer-1 LLM enrichment pass).
    * ``BaseAgent.summarize_issues`` writes a templated string and skips
      the LLM call entirely.

    Required gap-detection / strategy / synthesis-deliberation /
    report-narrative LLM calls are left intact so remediation can still
    work on its full input.
    """
    from agents_demo import _enrichment as enrichment_module
    from agents_demo.base_agent import BaseAgent

    def _identity_enrich(
        agent: Any, issues: list[Any], df: Any, allowed_types: set[str]
    ) -> list[Any]:
        agent.log("act", f"LLM enrichment skipped (lean mode) -- {len(issues)} det issues")
        return list(issues)

    def _template_summary(self: BaseAgent, issues: list[Any], summary_attr: str, noun: str) -> None:
        text = f"{len(issues)} {noun} issue(s) found (lean-mode summary)."
        setattr(self.state, summary_attr, text)
        self.log("reply", text)

    enrichment_module.enrich_with_llm = _identity_enrich
    BaseAgent.llm_enrich_issues = (  # type: ignore[method-assign]
        lambda self, issues, df, allowed_types: _identity_enrich(self, issues, df, allowed_types)
    )
    BaseAgent.summarize_issues = _template_summary  # type: ignore[method-assign]


def run(csv_path: Path, sample: int | None) -> dict[str, Any]:
    if sample is not None and sample > 0:
        df = pd.read_csv(csv_path)
        if len(df) > sample:
            df = df.sample(n=sample, random_state=42).reset_index(drop=True)
            tmp = csv_path.parent / f".__sampled_{csv_path.stem}_{sample}.csv"
            df.to_csv(tmp, index=False)
            csv_path = tmp
            print(f"  using sampled copy at {tmp.name} (n={len(df)})")

    graph = build_pipeline_graph(settings, with_checkpointer=False)
    initial_state = {"source_path": str(csv_path)}
    final_chunk: dict[str, Any] = {}
    t0 = time.monotonic()
    last_keys: set[str] = set()
    for chunk in graph.stream(initial_state, stream_mode="values"):
        new_keys = set(chunk.keys()) - last_keys
        if new_keys:
            print(f"  + state keys: {sorted(new_keys)}")
        last_keys = set(chunk.keys())
        final_chunk = chunk
    elapsed = time.monotonic() - t0

    state = state_from_dict(final_chunk)
    issue_types = Counter(issue["type"] for issue in state.prioritized_issues)
    fix_actions = Counter(f.get("action", "?") for f in state.fix_log)
    fix_types = Counter(f.get("issue_type", "?") for f in state.fix_log)
    report_payload = serialize_report(state.final_report)
    parsed = json.loads(report_payload)
    return {
        "elapsed_s": round(elapsed, 1),
        "reliability_before": state.reliability_score_before,
        "reliability_after": state.reliability_score_after,
        "issue_count": len(state.prioritized_issues),
        "issue_types": dict(issue_types),
        "fix_log_count": len(state.fix_log),
        "fix_actions": dict(fix_actions),
        "fix_types": dict(fix_types),
        "gap_issues_count": len(state.gap_issues),
        "deliberation_logged": len(state.deliberation_log),
        "human_review_items": len(state.human_review_items),
        "dimension_trajectory_checkpoints": list(state.dimension_trajectory.keys()),
        "report_title": parsed.get("title", ""),
        "report_summary_first_300": parsed.get("executive_summary", "")[:300],
        "df_raw_rows": len(state.df_raw) if state.df_raw is not None else 0,
        "df_cleaned_rows": (len(state.df_cleaned) if state.df_cleaned is not None else None),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--sample", type=int, default=None, help="Optional row sample size.")
    parser.add_argument("--label", type=str, default=None, help="Display label for the run.")
    parser.add_argument(
        "--lean-llm",
        action="store_true",
        help="Diagnostic mode: skip LLM enrichment + summarize calls.",
    )
    args = parser.parse_args()
    if args.lean_llm:
        print("[diagnostic] lean-llm mode: enrich/summarize LLM calls disabled.")
        _install_lean_llm_patches()
    label = args.label or args.csv_path.name
    print(f"=== {label}: {args.csv_path} (sample={args.sample}) ===")
    result = run(args.csv_path, args.sample)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
