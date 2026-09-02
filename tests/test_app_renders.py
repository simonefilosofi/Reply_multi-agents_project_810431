"""Renders the Streamlit gate over a fully populated state, so a layout that reads a field the
pipeline no longer produces fails here rather than in front of whoever is approving fixes. The
app is the only surface where a rename in the state is not caught by the deterministic tests, and
it is the one the reviewer sees. Nothing here calls a model: the state is built by hand."""
from __future__ import annotations

import pandas as pd
import pytest
from pathlib import Path

from streamlit.testing.v1 import AppTest

_APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")

from noipa_dq.models import (
    AnomalyEntry,
    AnomalyReport,
    ColumnPayload,
    DuplicateResolution,
    FixProposal,
    FormatViolation,
    ImputationHint,
    Operation,
    UnaddressedViolations,
    ValidationReport,
)
from noipa_dq.state import PipelineState

_CLEANER = "def clean_value(value):\n    return str(value).strip()\n"


def _state() -> PipelineState:
    frame = pd.DataFrame({
        "id": [f"r{i}" for i in range(30)],
        "rata": [202401 + (i % 3) for i in range(30)],
        "imposta": ["IRPEF", None] * 15,
        "spesa": [1000.0 + i for i in range(30)],
    })
    return PipelineState(
        dataset=frame,
        dataset_path="spesa.csv",
        detected_domain="Trattamento_economico",
        detected_language="it",
        payload=[
            ColumnPayload(column_name=str(c), description="d", dtype=str(frame[c].dtype),
                          placeholders=["n.d."], related_columns=["rata"])
            for c in frame.columns
        ],
        validation_reports=[
            ValidationReport(column_name="imposta", violations=[FormatViolation(
                column_name="imposta", row_index=-1, value=15,
                expected_pattern="missing value", kind="completeness", affected_rows=15)]),
            ValidationReport(column_name="rata", violations=[FormatViolation(
                column_name="rata", row_index=2, value="MAR-2024",
                expected_pattern="YYYYMM", kind="format")]),
        ],
        anomaly_reports=[
            AnomalyReport(column_name="spesa", method="iqr",
                          anomalies=[AnomalyEntry(row_index=1, value=99999.0, reason="above")],
                          stats={"detected": 1, "q1": 1.0, "q3": 9.0,
                                 "lower_bound": 0.0, "upper_bound": 10.0},
                          comment="a heavy right tail"),
            AnomalyReport(column_name="imposta", method="rare_category",
                          anomalies=[AnomalyEntry(row_index=3, value="Altro", reason="rare")],
                          stats={"detected": 1, "distinct_values": 4, "threshold": 3,
                                 "top_values": [{"value": "IRPEF", "count": 15, "pct": 50.0}]},
                          comment="one rare label"),
        ],
        duplicate_resolutions=[DuplicateResolution(
            group=["spesa", "SPESA TOTALE"], data_survivor="SPESA TOTALE",
            canonical_name="spesa", rationale="r", dropped=["spesa"],
            cells_backfilled=2, cells_overwritten={"spesa": 37})],
        auto_remediations=[{"column": "rata", "operation": "normalize_period",
                            "cells_changed": 414, "rationale": "layouts rewritten"}],
        proposed_fixes=[
            FixProposal(id="g1_f1", description="Drop note", rationale="almost empty",
                        affected_columns=["imposta"], estimated_rows_affected=15,
                        operations=[Operation(kind="drop_column", column="imposta")]),
            FixProposal(id="g1_f2", description="Clean rata", rationale="normalise the period",
                        affected_columns=["rata"], estimated_rows_affected=414,
                        operations=[Operation(kind="apply_generated_function", column="rata",
                                              source=_CLEANER)]),
        ],
        fix_groups={"g1": ["rata", "imposta"]},
        inferred_format_specs={"rata": {"source": "deterministic",
                                        "final_spec": {"type": "regex", "pattern": r"^\d{6}$"}}},
        imputation_hints={"imposta": ImputationHint(
            target_column="imposta", predictor_columns=["rata"], mapping={"202401": "IRPEF"},
            path="raw", purity=0.99, coverage=0.9, confidence="strict")},
        unaddressed_violations=[UnaddressedViolations(
            group_id="g1", columns=["imposta"], violation_ids=["v1"],
            reason="no column determines it", affected_rows=15,
            affected_by_column={"imposta": 15}, source="model")],
        completeness={"by_column": {c: {"nulls": 0, "total": 30, "completeness": 1.0}
                                    for c in ("id", "rata", "spesa")}
                      | {"imposta": {"nulls": 15, "total": 30, "completeness": 0.5}},
                      "overall": 0.875, "rows": 30, "sparse_columns": []},
        reliability={
            "as_delivered": {"dimensions": ["completeness"],
                             "before": {"score": 0.75, "components": {"completeness": 0.75},
                                        "weights": {"completeness": 1.0}},
                             "after": {"score": 0.99, "components": {"completeness": 0.99},
                                       "weights": {"completeness": 1.0}}},
            "like_for_like": {}, "dimensions_compared": ["completeness"],
            "dimensions_excluded": ["validity"],
        },
        errors=["apply_fixes:g1_f9: missing deps"],
    )


def _app(**session) -> AppTest:
    app = AppTest.from_file(_APP, default_timeout=120)
    for key, value in session.items():
        app.session_state[key] = value
    return app.run()


def test_the_landing_page_renders_before_anything_is_uploaded():
    app = AppTest.from_file(_APP, default_timeout=120).run()

    assert not app.exception
    assert any("Data quality for NoiPA" in block.value for block in app.markdown)


def test_every_tab_renders_over_a_populated_state():
    app = _app(pipeline_state=_state(), source_name="spesa.csv",
               timings={"Profiler": 9.3, "Semantic": 62.4})

    assert not app.exception
    assert [tab.label for tab in app.tabs] == [
        "Overview", "Findings", "Review and apply", "Report"
    ]


def test_the_headline_figures_are_shown():
    app = _app(pipeline_state=_state(), source_name="spesa.csv")

    values = {metric.label: metric.value for metric in app.metric}
    assert values["Rows"] == "30"
    assert values["Columns"] == "4"
    assert values["Proposals"] == "2"


def test_each_proposal_offers_the_three_decisions():
    app = _app(pipeline_state=_state(), source_name="spesa.csv")

    labels = [button.label for button in app.button]
    for decision in ("Accept", "Reject", "Revise"):
        assert labels.count(decision) == 2


def test_accepting_a_proposal_is_recorded():
    app = _app(pipeline_state=_state(), source_name="spesa.csv")

    next(b for b in app.button if b.label == "Accept").click().run()

    assert not app.exception
    assert "accepted" in app.session_state["fix_decisions"].values()


def test_a_decided_proposal_no_longer_awaits_one():
    app = _app(pipeline_state=_state(), source_name="spesa.csv",
               fix_decisions={"g1_f1": "rejected"})

    values = {metric.label: metric.value for metric in app.metric}
    assert values["Rejected"] == "1"
    assert values["Awaiting a decision"] == "1"


def test_the_run_records_no_error_when_the_state_carries_one():
    app = _app(pipeline_state=_state(), source_name="spesa.csv")

    assert not app.exception
    assert any("missing deps" in warning.value for warning in app.warning)


@pytest.mark.parametrize("missing", ["anomaly_reports", "duplicate_resolutions",
                                     "auto_remediations", "unaddressed_violations"])
def test_a_section_with_nothing_to_say_does_not_break_the_page(missing):
    app = _app(pipeline_state=_state().model_copy(update={missing: []}),
               source_name="spesa.csv")

    assert not app.exception


def test_a_state_with_no_proposals_still_renders_the_gate():
    app = _app(pipeline_state=_state().model_copy(update={"proposed_fixes": []}),
               source_name="spesa.csv")

    assert not app.exception
    assert any("No remediation proposed" in info.value for info in app.info)
