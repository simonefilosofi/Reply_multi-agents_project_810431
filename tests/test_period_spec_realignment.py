"""Pins that normalising a period column carries its format spec along with it. A column's spec is
inferred by format_consistency, which runs before auto_remediation; when auto_remediation then
rewrites the column to the canonical YYYYMM form, the spec inferred from the layout the file
arrived in no longer describes it. Left alone, the residual check at report time fails every row
the node just corrected and reports a clean column as wholly non-conforming - measured on
ritenuteSindacali as 11,657 spurious format violations against 984 genuinely detected. The
realignment mirrors _realign_range_bounds, which already does the same for a rounded range."""
from __future__ import annotations

import pandas as pd

from agents.auto_remediation import _realign_period_specs, auto_remediation_node
from models import ColumnPayload
from state import PipelineState
from tools.normalize_period_format import CANONICAL_STRFTIME
from tools.validate_format import specs_by_column, validate_format


def _spec(strftime_pattern: str) -> dict:
    """A period column reaches auto_remediation as a date spec carrying no day component; that is
    what marks it as a period."""
    return {
        "source": "inferred",
        "final_spec": {"type": "date", "strftime_pattern": strftime_pattern},
    }


def test_a_normalized_period_column_gets_the_canonical_spec():
    realigned = _realign_period_specs(
        {"mese_competenza": _spec("%Y-%m")}, {"mese_competenza"}
    )

    assert realigned["mese_competenza"]["final_spec"] == {
        "type": "date", "strftime_pattern": CANONICAL_STRFTIME,
    }


def test_realignment_keeps_the_rest_of_the_entry():
    realigned = _realign_period_specs(
        {"mese_competenza": _spec("%Y-%m")}, {"mese_competenza"}
    )

    assert realigned["mese_competenza"]["source"] == "inferred"


def test_a_column_that_was_not_normalized_is_untouched():
    specs = {"altro": _spec("%Y-%m")}

    assert _realign_period_specs(specs, set()) == specs
    assert _realign_period_specs(specs, {"mese_competenza"})["altro"] == specs["altro"]


def test_the_canonical_spec_accepts_what_normalisation_produces():
    normalised = pd.Series(["202401", "202412", "202406"])
    spec = specs_by_column({"p": {"final_spec": {"type": "date", "strftime_pattern": CANONICAL_STRFTIME}}})

    assert validate_format("p", normalised, spec["p"]).violations == []


def test_the_canonical_spec_still_reports_what_normalisation_could_not_parse():
    partly = pd.Series(["202401", "not a period", "202403"])
    spec = specs_by_column({"p": {"final_spec": {"type": "date", "strftime_pattern": CANONICAL_STRFTIME}}})

    violations = validate_format("p", partly, spec["p"]).violations

    assert [v.value for v in violations] == ["not a period"]


def test_the_node_leaves_no_spurious_violation_on_the_column_it_rewrote():
    frame = pd.DataFrame({"mese_competenza": [f"2024-{month:02d}" for month in range(1, 13)]})
    state = PipelineState(
        dataset=frame,
        payload=[ColumnPayload(
            column_name="mese_competenza", description="accounting period",
            dtype="object", sample=list(frame["mese_competenza"]),
        )],
        surviving_columns=["mese_competenza"],
        inferred_format_specs={"mese_competenza": _spec("%Y-%m")},
    )

    result = auto_remediation_node(state)

    rewritten = result.dataset["mese_competenza"]
    assert list(rewritten) == [f"2024{month:02d}" for month in range(1, 13)]

    spec = specs_by_column(result.inferred_format_specs)["mese_competenza"]
    assert validate_format("mese_competenza", rewritten, spec).violations == []
