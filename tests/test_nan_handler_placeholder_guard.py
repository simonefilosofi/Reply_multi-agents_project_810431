"""Pins the refusal to empty a column through its placeholder list. A column matching a canonical
definition whose enum uses a different vocabulary - the registry says COMPARTO FUNZIONI CENTRALI,
the file says FUNZIONI CENTRALI - makes every value a spec violation, and the Semantic agent
forwards spec violations as placeholder candidates. Runs over two synthetic datasets erased
`comparto` entirely that way, 15,102 and 11,578 values, before the approval gate saw anything.
Legitimate unmasking across every dataset measured peaked at 3.9% of a column, so a list matching
far more of one is the unreliable party and is refused and reported rather than applied."""
from __future__ import annotations

import pandas as pd

from agents.nan_handler import nan_handler_node
from models import ColumnPayload
from state import PipelineState

_ENUM = ["FUNZIONI CENTRALI", "FUNZIONI LOCALI", "SANITA'", "ISTRUZIONE E RICERCA"]


def _state(frame: pd.DataFrame, placeholders: dict[str, list]) -> PipelineState:
    return PipelineState(
        dataset=frame,
        payload=[
            ColumnPayload(column_name=str(column), description="", dtype="",
                          placeholders=placeholders.get(str(column), []))
            for column in frame.columns
        ],
    )


def _column(values: list, n: int) -> list:
    return [values[i % len(values)] for i in range(n)]


def test_a_placeholder_list_covering_the_whole_column_is_refused() -> None:
    frame = pd.DataFrame({"comparto": _column(_ENUM, 400)})

    result = nan_handler_node(_state(frame, {"comparto": _ENUM}))

    assert int(result.dataset["comparto"].isna().sum()) == 0
    assert list(result.dataset["comparto"]) == list(frame["comparto"])


def test_the_refusal_is_reported_rather_than_silent() -> None:
    frame = pd.DataFrame({"comparto": _column(_ENUM, 400)})

    result = nan_handler_node(_state(frame, {"comparto": _ENUM}))

    violations = [
        violation
        for report in result.validation_reports if report.column_name == "comparto"
        for violation in report.violations
        if "placeholder" in (violation.expected_pattern or "")
    ]
    assert len(violations) == 1
    assert violations[0].kind == "schema"


def test_a_realistic_placeholder_share_is_still_unmasked() -> None:
    values = _column(_ENUM, 388) + ["n.d."] * 8 + ["?"] * 4
    frame = pd.DataFrame({"comparto": values})

    result = nan_handler_node(_state(frame, {"comparto": ["n.d.", "?"]}))

    assert int(result.dataset["comparto"].isna().sum()) == 12


def test_a_column_whose_list_matches_nothing_is_untouched() -> None:
    frame = pd.DataFrame({"comparto": _column(_ENUM, 100)})

    result = nan_handler_node(_state(frame, {"comparto": ["n.d.", "unknown"]}))

    assert int(result.dataset["comparto"].isna().sum()) == 0
    assert not [
        violation
        for report in result.validation_reports
        for violation in report.violations
        if "placeholder" in (violation.expected_pattern or "")
    ]


def test_the_guard_is_applied_per_column() -> None:
    frame = pd.DataFrame({
        "comparto": _column(_ENUM, 400),
        "provincia": _column(["RM", "MI", "NA"], 388) + ["-"] * 12,
    })

    result = nan_handler_node(
        _state(frame, {"comparto": _ENUM, "provincia": ["-"]})
    )

    assert int(result.dataset["comparto"].isna().sum()) == 0
    assert int(result.dataset["provincia"].isna().sum()) == 12
