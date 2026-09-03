"""Holds the README and the notebook to the runs they describe. Every figure quoted in those two
documents comes from a recorded run under reports/runs/, and nothing else checks that the sentence and the
artefact still agree: a re-recorded run silently leaves the prose describing the previous one, which
is how the published numbers came to describe a run whose artefacts no longer existed. Each check
below derives the string from the artefact and asserts the document contains it, so a stale figure
fails the suite rather than reaching a reader.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "reports" / "runs"
README = (ROOT / "README.md").read_text(encoding="utf-8")
NOTEBOOK = "\n".join(
    "".join(cell["source"])
    for cell in json.loads((ROOT / "notebooks" / "main.ipynb").read_text(encoding="utf-8"))["cells"]
)


def _run(name: str) -> dict:
    return json.loads((RUNS / name / f"{name}.json").read_text(encoding="utf-8"))


def _timings(name: str) -> dict:
    return json.loads((RUNS / name / "timings.json").read_text(encoding="utf-8"))


def _second_pass() -> dict[str, dict]:
    payload = json.loads((RUNS / "second_pass_timings.json").read_text(encoding="utf-8"))
    return {name: stages for name, stages in payload.items() if not name.startswith("_")}


def _detected(name: str) -> int:
    return sum(_run(name)["violations_by_kind_detected"].values())


def _residual(name: str) -> int:
    return sum(_run(name)["violations_by_kind_residual"].values())


def _like_for_like(name: str) -> tuple[float, float]:
    block = _run(name)["quality"]["like_for_like"]
    return block["before"]["score"], block["after"]["score"]


def test_the_readme_quotes_the_detection_totals_of_the_recorded_runs() -> None:
    for name in ("spesa", "attivazioniCessazioni", "ritenuteSindacali"):
        assert f"{_detected(name):,}" in README, f"{name} detected total is stale in the README"
        assert f"{_residual(name):,}" in README, f"{name} residual total is stale in the README"


def test_the_readme_quotes_the_recorded_reliability_scores() -> None:
    for name in ("spesa", "attivazioniCessazioni", "ritenuteSindacali"):
        before, after = _like_for_like(name)
        assert f"{before:.4f}" in README, f"{name} like-for-like before is stale in the README"
        assert f"{after:.4f}" in README, f"{name} like-for-like after is stale in the README"


def test_the_readme_quotes_the_recorded_change_counts() -> None:
    for name in ("spesa", "attivazioniCessazioni", "ritenuteSindacali"):
        summary = _run(name)["changes_summary"]
        assert f"{summary['total_cells_changed']:,}" in README, f"{name} cells changed is stale"


def test_the_readme_quotes_the_recorded_runtimes() -> None:
    for name in ("spesa", "attivazioniCessazioni", "ritenuteSindacali"):
        assert f"{sum(_timings(name).values()):.1f}s" in README, f"{name} runtime is stale"


def test_the_readme_quotes_the_second_pass_runtimes() -> None:
    """Section 4.6 reports a range, so the second recording is held to the README exactly as the
    canonical one is: both its totals and the per-stage figures the section names must still match."""
    for name, timings in _second_pass().items():
        assert f"{sum(timings.values()):.1f}s" in README, f"{name} second-pass runtime is stale"

    spesa = _second_pass()["spesa"]
    cheap = ("baseline_builder", "nan_handler", "duplicate_row", "auto_remediation")
    assert f"{sum(spesa[stage] for stage in cheap):.1f} seconds" in README.replace("**", "")
    assert f"{spesa['unified'] / sum(spesa.values()) * 100:.0f}%" in README.replace("**", "")


def test_the_readme_quotes_the_spesa_run_in_detail() -> None:
    spesa = _run("spesa")
    quality = spesa["quality"]
    raw, final = quality["snapshots"]["raw"], quality["snapshots"]["final"]

    for figure in (
        f"{raw['rows']:,}", f"{raw['null_cells']:,}", f"{final['null_cells']:,}",
        f"{quality['hidden_defects_unmasked']['disguised_nulls_unmasked']:,}",
        f"{spesa['changes_summary']['by_source']['auto_remediation']:,}",
        f"{quality['as_delivered']['before']['score']:.4f}",
        f"{quality['as_delivered']['after']['score']:.4f}",
        str(raw["completeness"]), str(final["completeness"]),
    ):
        assert figure in README, f"{figure} no longer matches the recorded spesa run"


def test_the_readme_states_how_many_proposals_reached_the_reviewer() -> None:
    spesa = _run("spesa")

    assert f"| Proposals put to the reviewer | {len(spesa['proposed_remediations'])} |" in README
    assert f"| Proposals approved and applied | {len(spesa['applied_fix_ids'])} " in README


def test_the_readme_states_where_generated_code_actually_ran() -> None:
    """The sandbox claim is the one a reader is most entitled to check, and the only one that
    depends on a third party being reachable when the run was recorded."""
    trials = [entry for name in ("spesa", "attivazioniCessazioni", "ritenuteSindacali")
              for entry in (_run(name).get("generated_function_runs") or [])]
    in_sandbox = sum(1 for entry in trials if entry["executor"] == "e2b" and entry["ok"])

    assert len(trials) == in_sandbox, "a trial fell back to the local cage; the README says none did"
    assert "eight of eight" in README


@pytest.mark.parametrize("name", ("spesa", "attivazioniCessazioni", "ritenuteSindacali"))
def test_the_notebook_names_the_runs_it_replays(name: str) -> None:
    assert f'"runs" / "{name}"' in NOTEBOOK


def test_the_notebook_quotes_the_reproducibility_evidence_it_shows() -> None:
    """Section 16 makes a claim about two recordings agreeing. The half that is checkable here is
    that the figures it names still describe the run the notebook ships with."""
    spesa = _run("spesa")
    quality = spesa["quality"]

    for figure in (
        f"{quality['snapshots']['raw']['null_cells']:,}",
        f"{quality['hidden_defects_unmasked']['disguised_nulls_unmasked']:,}",
        str(quality["snapshots"]["final"]["completeness"]),
    ):
        assert figure in NOTEBOOK, f"{figure} no longer matches the recorded spesa run"


def test_the_readme_quotes_the_pinned_invariants_it_summarises() -> None:
    """The recovery figures in Section 1.6 come from checks/invariants.json. Pinning them here means
    a re-pin cannot leave the prose describing the previous baseline."""
    pinned = json.loads((ROOT / "tests" / "acceptance" / "invariants.json").read_text(encoding="utf-8"))

    recovered = [pair["ok"] for run in pinned.values()
                 for pair in run["numeric_recovery"].values() if pair.get("messy")]
    checked = [run["date_recovery"]["checked"] for run in pinned.values()]
    for figure in recovered + checked:
        assert f"{figure:,}" in README, f"{figure} no longer matches the pinned baseline"

    for run in pinned.values():
        authority = run["authority_overwrites"]
        if authority.get("applicable"):
            assert authority["clean_month_overwritten"] == 0
            assert authority["clean_year_overwritten"] == 0
            assert f"{authority['malformed_month_filled']:,}" in README
            assert f"{authority['malformed_year_filled']:,}" in README
