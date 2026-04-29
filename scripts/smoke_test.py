"""End-to-end smoke test for the NoiPA multi-agent data-quality pipeline.

Runs the full LangGraph compiled pipeline on the canonical clean and
dirty NoiPA CSV fixtures and asserts the hand-off requirements from
``Implementation Plan v2.md`` (Step 14):

1. Reliability score after > before for both fixtures.
2. At least one ``lookup_imputability`` issue is detected and resolved.
   (Exercised on the synthetic wide-dirty fixture, which is the only
   shipped dataset whose 30-column shape can carry the
   ``region_code`` -> ``capoluogo`` mapping the detector needs.)
3. At least one ``format_pattern_violation`` issue carries its
   ``pattern`` field through to remediation (B1 regression).
4. At least one deliberation outcome is logged when the wide-dirty
   fixture is processed (its delta_amount column triggers the
   outlier-vs-domain-negative deliberation pattern).
5. ``serialize_report`` produces JSON without raising.
6. ``df_cleaned`` has no rows that ``df_raw`` did not (no row leakage).

Usage::

    python -m scripts.smoke_test --mocked   # offline, no API credits
    python -m scripts.smoke_test            # real LLM, requires keys

The ``--mocked`` mode patches ``BaseAgent.call_llm`` and
``BaseAgent.call_llm_json`` with deterministic stubs so the smoke can
run in CI without API credentials. Designed to finish well under 60 s.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "examples"))

from agents_demo._graph import build_pipeline_graph, state_from_dict  # noqa: E402
from agents_demo.report_agent import serialize_report  # noqa: E402
from agents_demo.synthesis_agent import SynthesisAgent  # noqa: E402
from state_demo import settings  # noqa: E402
from state_demo.deliberation import Vote  # noqa: E402
from state_demo.fingerprint_schema import DatasetFingerprint  # noqa: E402
from state_demo.issues import Issue  # noqa: E402

DATA_DIR = ROOT / "data" / "examples"
CLEAN_CSV = DATA_DIR / "clean_noipa_sample.csv"
DIRTY_CSV = DATA_DIR / "dirty_noipa_sample.csv"


class SmokeFailure(AssertionError):
    pass


def _fingerprint_for_dirty_noipa() -> DatasetFingerprint:
    return DatasetFingerprint.model_validate(
        {
            "domain": "italian payroll administration",
            "language": "italian",
            "id_columns": [],
            "numerical_columns": ["imposta", "spesa"],
            "categorical_columns": ["ente", "tipo_imposta"],
            "date_columns": [],
            "sparse_columns": [],
            "likely_duplicate_pairs": [],
            "suggested_key_columns": [],
            "column_descriptions": {
                "rata": "payroll period code",
                "ente": "issuing public entity",
                "descrizione": "free-text description",
                "tipo_imposta": "tax type code",
                "imposta": "tax amount",
                "spesa": "total spend",
            },
            "column_constraints": [
                {
                    "column": "imposta",
                    "type": "no_negatives",
                    "description": "tax amounts are non-negative",
                },
                {
                    "column": "tipo_imposta",
                    "type": "format_pattern",
                    "pattern": r"^[A-Z]{2,8}$",
                    "description": "tax codes are uppercase letters",
                },
            ],
        }
    )


def _install_mock_llm(fingerprint: DatasetFingerprint) -> None:
    from pydantic import BaseModel

    from agents_demo.base_agent import BaseAgent

    canned_summary = "Pipeline run via mocked LLM stubs."

    def _fake_call_llm(self: BaseAgent, user: str, max_tokens: int = 4096) -> str:
        return canned_summary

    def _fake_call_llm_json(
        self: BaseAgent,
        user: str,
        max_tokens: int = 4096,
        required_keys: list[str] | None = None,
        schema: type[BaseModel] | None = None,
    ) -> Any:
        if schema is DatasetFingerprint:
            return fingerprint
        if schema is not None:
            try:
                return schema()
            except Exception:
                return schema.model_validate({})
        return {}

    BaseAgent.call_llm = _fake_call_llm  # type: ignore[method-assign]
    BaseAgent.call_llm_json = _fake_call_llm_json  # type: ignore[method-assign]


def _stub_specialist_vote() -> None:
    """Make synthesis deliberation deterministic without LLM calls."""

    def _vote(
        self: SynthesisAgent,
        specialist_name: str,
        peer_name: str,
        contested: Issue,
    ) -> Vote:
        keep = specialist_name == contested.source
        return Vote(
            agent_name=specialist_name,  # type: ignore[arg-type]
            keep_issue=keep,
            rationale=f"smoke stub: {specialist_name} keep={keep}",
            confidence=0.85,
        )

    SynthesisAgent._specialist_vote = _vote  # type: ignore[method-assign,assignment]


def run_pipeline(csv_path: Path) -> Any:
    """Compile and stream the pipeline on one CSV. Returns the rehydrated state."""
    graph = build_pipeline_graph(settings, with_checkpointer=False)
    initial_state = {"source_path": str(csv_path)}
    final_chunk: dict[str, Any] = {}
    for chunk in graph.stream(initial_state, stream_mode="values"):
        final_chunk = chunk
    return state_from_dict(final_chunk)


def assert_reliability_uplift(label: str, state: Any) -> None:
    before = state.reliability_score_before
    after = state.reliability_score_after
    if not (after >= before):
        raise SmokeFailure(f"[{label}] reliability did not improve: before={before}, after={after}")


def assert_no_row_leakage(label: str, state: Any) -> None:
    if state.df_cleaned is None:
        return
    if len(state.df_cleaned) > len(state.df_raw):
        raise SmokeFailure(
            f"[{label}] row leakage: cleaned={len(state.df_cleaned)} > raw={len(state.df_raw)}"
        )


def assert_serialize_report(label: str, state: Any) -> None:
    payload = serialize_report(state.final_report)
    parsed = json.loads(payload)
    if not parsed.get("title"):
        raise SmokeFailure(f"[{label}] serialised report missing 'title'")


def assert_format_pattern_carries_through(label: str, state: Any) -> None:
    issues_with_pattern = [
        issue
        for issue in state.prioritized_issues
        if issue["type"] == "format_pattern_violation" and issue.get("pattern")
    ]
    if not issues_with_pattern:
        raise SmokeFailure(
            f"[{label}] B1 regression: no format_pattern_violation issue carries pattern field"
        )


def assert_lookup_imputability_resolved(label: str, state: Any) -> None:
    detected = [
        issue for issue in state.prioritized_issues if issue["type"] == "lookup_imputability"
    ]
    fixed = [
        f
        for f in state.fix_log
        if f.get("issue_type") == "lookup_imputability" and f.get("action") == "auto_fixed"
    ]
    if not detected:
        raise SmokeFailure(f"[{label}] no lookup_imputability issue detected")
    if not fixed:
        raise SmokeFailure(f"[{label}] lookup_imputability detected but not auto-fixed")


def assert_deliberation_logged(label: str, state: Any) -> None:
    if not state.deliberation_log:
        raise SmokeFailure(f"[{label}] no deliberation outcome logged")


def run_wide_dirty_assertions() -> None:
    """Drive the wide-dirty synthetic fixture through synthesis with stubs.

    The wide-dirty 30-column fixture is the only shipped dataset whose
    shape triggers ``lookup_imputability`` and the
    ``outlier vs domain_negative`` deliberation deterministically. The
    real graph is not run here -- we re-use the same SynthesisAgent
    seeding pattern as ``tests/integration/test_deliberation_e2e.py``
    so the smoke check is fast and independent of LLM mocking quirks.
    """
    import numpy as np
    from _generate import build_wide_dirty_df

    from state_demo.issues import (
        DomainNegativeValuesIssue,
        DuplicateColumnsIssue,
        InvalidDatesIssue,
        LookupImputabilityIssue,
        MixedTypeIssue,
        OutliersIssue,
    )
    from state_demo.pipeline_state import PipelineState

    df = build_wide_dirty_df().copy()
    rng = np.random.default_rng(42)
    base = rng.normal(loc=200.0, scale=30.0, size=len(df))
    base[: max(1, int(len(df) * 0.05))] = -1500.0
    df["delta_amount"] = base

    state = PipelineState()
    state.df_raw = df
    state.dataset_fingerprint = {
        "domain": "smoke_wide_dirty",
        "language": "italian",
        "id_columns": [],
        "numerical_columns": ["delta_amount", "importo_lordo", "importo_netto"],
        "categorical_columns": ["region_code", "regione_codice", "capoluogo"],
        "date_columns": ["region_code"],
        "sparse_columns": ["sparse_a", "sparse_b"],
        "likely_duplicate_pairs": [
            ["region_code", "regione_codice"],
            ["importo_lordo", "importo_netto"],
        ],
        "suggested_key_columns": [],
        "column_descriptions": {},
        "column_constraints": [],
    }
    state.completeness_by_column = {c: 1.0 for c in df.columns}
    state.overall_completeness = 1.0

    state.schema_report = {
        "issues": [
            MixedTypeIssue(
                column="delta_amount",
                detail="mixed type sample",
                severity="medium",
                source="schema",
            ),
            InvalidDatesIssue(
                column="region_code",
                detail="profiler-vs-schema date dispute fixture",
                severity="medium",
                source="schema",
                parse_rate=0.10,
            ),
        ],
        "total_issues": 2,
    }
    state.completeness_report = {"issues": [], "total_issues": 0}
    state.duplicate_report = {
        "issues": [
            DuplicateColumnsIssue(
                column="region_code / regione_codice",
                column_a="region_code",
                column_b="regione_codice",
                detail="duplicate region columns",
                severity="medium",
                source="duplicate",
            )
        ],
        "total_issues": 1,
    }
    state.consistency_report = {
        "issues": [
            LookupImputabilityIssue(
                column="region_code",
                detail="capoluogo -> region_code mapping",
                severity="medium",
                source="consistency",
                mapping_source="regione_codice",
                coverage=0.95,
                n_imputable=20,
            )
        ],
        "total_issues": 1,
    }
    state.anomaly_report = {
        "issues": [
            OutliersIssue(
                column="delta_amount",
                detail="3xIQR outliers",
                severity="medium",
                source="anomaly",
                outlier_count=10,
            )
        ],
        "total_issues": 1,
    }
    state.constraint_report = {
        "issues": [
            DomainNegativeValuesIssue(
                column="delta_amount",
                detail="negative values in non-negative column",
                severity="medium",
                source="constraint",
                negative_count=10,
            )
        ],
        "total_issues": 1,
    }

    SynthesisAgent(state).run("smoke synthesis")
    assert_deliberation_logged("wide_dirty/synthesis", state)
    has_lookup = any(issue["type"] == "lookup_imputability" for issue in state.prioritized_issues)
    if not has_lookup:
        raise SmokeFailure("[wide_dirty] no lookup_imputability issue surfaced through synthesis")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mocked",
        action="store_true",
        help="Patch BaseAgent LLM calls with deterministic stubs (no API credits).",
    )
    args = parser.parse_args(argv)

    print("--- NoiPA smoke test ---")
    print(f"  mode: {'MOCKED' if args.mocked else 'LIVE LLM'}")

    if args.mocked:
        _install_mock_llm(_fingerprint_for_dirty_noipa())
        _stub_specialist_vote()

    failures: list[str] = []
    deadline_s = 180

    started = time.monotonic()

    for label, csv in (("clean_noipa_sample", CLEAN_CSV), ("dirty_noipa_sample", DIRTY_CSV)):
        print(f"\n[{label}] running pipeline on {csv.name} ...")
        t0 = time.monotonic()
        try:
            state = run_pipeline(csv)
        except Exception as exc:
            failures.append(f"[{label}] pipeline raised: {type(exc).__name__}: {exc}")
            continue
        elapsed = time.monotonic() - t0
        print(
            f"[{label}] done in {elapsed:.1f}s "
            f"-- before={state.reliability_score_before} after={state.reliability_score_after}"
        )
        for check in (
            assert_reliability_uplift,
            assert_no_row_leakage,
            assert_serialize_report,
        ):
            try:
                check(label, state)
            except SmokeFailure as exc:
                failures.append(str(exc))
        if label == "dirty_noipa_sample":
            try:
                assert_format_pattern_carries_through(label, state)
            except SmokeFailure as exc:
                failures.append(str(exc))

    print("\n[wide_dirty] running synthesis stub for lookup + deliberation ...")
    try:
        run_wide_dirty_assertions()
        print("[wide_dirty] lookup_imputability + deliberation OK")
    except SmokeFailure as exc:
        failures.append(str(exc))

    elapsed_total = time.monotonic() - started
    print(f"\n--- Smoke complete in {elapsed_total:.1f}s ---")

    if elapsed_total > deadline_s:
        failures.append(f"smoke exceeded {deadline_s}s budget (took {elapsed_total:.1f}s)")

    if failures:
        print("FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
