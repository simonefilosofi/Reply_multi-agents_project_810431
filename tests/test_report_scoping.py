"""Pins the mapping from a remediated column back to the name it carried before remediation. The like-for-like comparison is only honest if that mapping survives both the canonical name elected for a duplicate-column group and any rename an approved fix applied; a column that fails to map is silently dropped from the comparison, and the columns most likely to be renamed are exactly the badly named ones whose improvement the figure is supposed to show."""
from __future__ import annotations

import pandas as pd

from noipa_dq.agents.report_generator import _origin_columns, _scope_metrics
from noipa_dq.models import DuplicateResolution, FixProposal, Operation
from noipa_dq.state import PipelineState


def _state(**overrides) -> PipelineState:
    base = {"dataset": pd.DataFrame({"a": [1]}), "duplicate_resolutions": [], "proposed_fixes": [],
            "applied_fix_ids": []}
    return PipelineState(**{**base, **overrides})


def _rename(fix_id: str, column: str, new_name: str) -> FixProposal:
    return FixProposal(
        id=fix_id,
        description="",
        rationale="",
        operations=[Operation(kind="rename_column", column=column, new_name=new_name)],
    )


def test_a_column_nothing_touched_maps_to_itself() -> None:
    assert _origin_columns(_state()).get("rata", "rata") == "rata"


def test_a_canonical_name_maps_to_itself() -> None:
    """The snapshot the comparison is measured against is taken after the duplicate-column
    election, so it already carries canonical names. Mapping them back to the column that
    originally held the data would point at a name the snapshot no longer contains, and the
    column would silently drop out of the comparison."""
    resolution = DuplicateResolution(
        group=["tipo_imposta", "Tipo Imposta"], data_survivor="Tipo Imposta",
        canonical_name="tipo_imposta", rationale="", dropped=["tipo_imposta"],
    )
    origins = _origin_columns(_state(duplicate_resolutions=[resolution]))
    assert origins.get("tipo_imposta", "tipo_imposta") == "tipo_imposta"


def test_an_applied_rename_maps_back_to_the_original_name() -> None:
    state = _state(proposed_fixes=[_rename("g1_f1", "aggregation-time", "aggregation_time")],
                   applied_fix_ids=["g1_f1"])
    assert _origin_columns(state)["aggregation_time"] == "aggregation-time"


def test_a_rejected_rename_is_not_mapped() -> None:
    state = _state(proposed_fixes=[_rename("g1_f1", "aggregation-time", "aggregation_time")],
                   applied_fix_ids=[])
    assert "aggregation_time" not in _origin_columns(state)


def test_a_column_elected_then_renamed_maps_back_only_to_its_canonical_name() -> None:
    resolution = DuplicateResolution(
        group=["SPESA TOTALE", "spesa"], data_survivor="SPESA TOTALE",
        canonical_name="spesa_totale", rationale="", dropped=["spesa"],
    )
    state = _state(duplicate_resolutions=[resolution],
                   proposed_fixes=[_rename("g1_f1", "spesa_totale", "spesa")],
                   applied_fix_ids=["g1_f1"])
    assert _origin_columns(state)["spesa"] == "spesa_totale"


def test_scoping_recomputes_validity_and_consistency_on_the_kept_columns() -> None:
    before = {
        "rows": 100,
        "null_by_column": {"kept": 10, "dropped": 90},
        "structural_defects": {"dropped": ["sparse"]},
        "checked_cells_by_column": {"kept": 200, "dropped": 300},
        "format_violations_by_column": {"kept": 20, "dropped": 100},
        "inconsistent_rows_by_column": {"kept": 5, "dropped": 40},
        "inconsistent_rows": 44,
        "checked_cells": 500,
        "validity": 0.76,
        "consistency": 0.56,
    }
    scoped = _scope_metrics(before, ["kept"])
    assert scoped["checked_cells"] == 200
    assert scoped["format_violations"] == 20
    assert scoped["validity"] == 0.9
    assert scoped["inconsistent_rows"] == 5
    assert scoped["consistency"] == 0.95


def test_scoping_never_claims_more_inconsistent_rows_than_the_whole_frame_had() -> None:
    before = {
        "rows": 10,
        "null_by_column": {"a": 0, "b": 0},
        "structural_defects": {},
        "checked_cells_by_column": {"a": 10, "b": 10},
        "format_violations_by_column": {},
        "inconsistent_rows_by_column": {"a": 6, "b": 6},
        "inconsistent_rows": 8,
    }
    assert _scope_metrics(before, ["a", "b"])["inconsistent_rows"] == 8
