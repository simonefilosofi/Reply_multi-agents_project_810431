"""Pins the recorded runs the notebook replays and the README draws its figures from. These files
are committed, so they can fall out of step with the code that renders them: a run recorded before a
change to tools/report_charts.py or tools/report_markdown.py keeps the old rendering, and nothing
else in the suite compares one report against another. That happened once already - a report
rendered mid-change carried neither the chart background nor the duplicate-detection row while its
neighbours did. These checks read only the committed artefacts, so they need no network and no key.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from noipa_dq.tools.report_charts import _AFTER, _BEFORE, _GRID, _INK, _LOW, _MUTED, _PAPER

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "reports" / "runs"
RECORDED = ("spesa", "attivazioniCessazioni", "ritenuteSindacali")
CHART_PALETTE = frozenset({_INK, _PAPER, _BEFORE, _AFTER, _GRID, _MUTED, _LOW})
_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_SVG = re.compile(r"<svg\b.*?</svg>", re.DOTALL)


def _report(name: str) -> Path:
    return RUNS / name / f"{name}.md"


@pytest.mark.parametrize("name", RECORDED)
def test_every_recorded_run_ships_the_files_the_notebook_reads(name: str) -> None:
    directory = RUNS / name
    for suffix in (".json", ".md", ".html", ".pdf"):
        assert (directory / f"{name}{suffix}").exists(), f"{name}{suffix} is missing from {directory}"
    assert (directory / "timings.json").exists(), f"timings.json is missing from {directory}"


@pytest.mark.parametrize("name", RECORDED)
def test_every_chart_paints_its_own_page(name: str) -> None:
    """A report rendered before the background was added reads as dark ink on a dark ground
    wherever it is embedded, and looks like a different palette beside its neighbours."""
    charts = _SVG.findall(_report(name).read_text(encoding="utf-8"))

    assert charts, f"{name} has no charts to check"
    for chart in charts:
        assert f"fill='{_PAPER}'" in chart[:400]


@pytest.mark.parametrize("name", RECORDED)
def test_no_report_strays_from_the_chart_palette(name: str) -> None:
    for chart in _SVG.findall(_report(name).read_text(encoding="utf-8")):
        assert set(_HEX.findall(chart)) <= CHART_PALETTE


@pytest.mark.parametrize("name", RECORDED)
def test_every_report_covers_the_same_five_areas(name: str) -> None:
    """The coverage table is the one place a reader checks the brief's five areas. A run rendered
    by older code silently drops whichever row that code did not have."""
    document = _report(name).read_text(encoding="utf-8")

    for area in ("Schema validation", "Completeness", "Consistency",
                 "Duplicate detection", "Anomaly detection", "Format validity"):
        assert f"| {area} " in document, f"{name} has no {area} row"


@pytest.mark.parametrize("name", RECORDED)
def test_the_timings_cover_the_whole_pipeline(name: str) -> None:
    timings = json.loads((RUNS / name / "timings.json").read_text(encoding="utf-8"))

    assert set(timings) == {
        "baseline_builder", "profiler", "semantic", "nan_handler", "duplicate_column",
        "format_consistency", "auto_remediation", "anomaly_detector", "unified",
        "apply_fixes", "duplicate_row", "report_generator",
    }
    assert all(seconds > 0 for seconds in timings.values())


@pytest.mark.parametrize("name", RECORDED)
def test_a_recorded_run_reports_no_error(name: str) -> None:
    payload = json.loads((RUNS / name / f"{name}.json").read_text(encoding="utf-8"))

    assert payload["errors"] == []
    assert set(payload["violations_by_kind_detected"]) == {
        "format", "completeness", "schema", "consistency", "uniqueness"
    }


@pytest.mark.parametrize("name", RECORDED)
def test_the_uniqueness_tally_matches_the_rows_it_counts(name: str) -> None:
    """The tally is the rows a snapshot measured as not unique. Pinning it against the measurements
    stored beside it means a committed artefact cannot carry a figure the shipped formula would not
    produce, whichever revision recorded it."""
    payload = json.loads((RUNS / name / f"{name}.json").read_text(encoding="utf-8"))
    snapshots = payload["quality"]["snapshots"]

    for label, snapshot in snapshots.items():
        counts = snapshot.get("violations_by_kind")
        if not counts:
            continue
        expected = int(snapshot["duplicate_rows"]) + int(snapshot["rows_in_key_conflict"])
        assert counts["uniqueness"] == expected, f"{name}/{label} claims {counts['uniqueness']}"

    assert payload["violations_by_kind_detected"] == snapshots["pre_remediation"]["violations_by_kind"]
    assert payload["violations_by_kind_residual"] == snapshots["final"]["violations_by_kind"]


def test_the_audit_trail_accounts_for_every_cell_the_report_claims() -> None:
    """The report says every changed cell is recorded with the stage responsible. That is checkable
    against the change log shipped beside it, and it is the claim a reviewer is most likely to test."""
    payload = json.loads((RUNS / "spesa" / "spesa.json").read_text(encoding="utf-8"))
    with (RUNS / "spesa" / "spesa.changes.csv").open(encoding="utf-8", newline="") as handle:
        entries = list(csv.DictReader(handle))

    assert len(entries) == payload["changes_summary"]["total_cells_changed"]
    assert all(entry["source"] for entry in entries), "a changed cell names no stage"
    assert {entry["source"] for entry in entries} == set(payload["changes_summary"]["by_source"])
