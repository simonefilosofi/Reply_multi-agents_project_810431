"""Pins the before-and-after summary the approval gate shows once fixes are applied. It listed the
columns the dataset had before, and looked each up by the same name afterwards, so an approved
rename produced a row for the old name with nothing beside it and no row for the new one. The
fixes had in fact been applied; only the table could not follow them, which read as the apply
having done nothing until it was pressed a second time."""
from __future__ import annotations

import pandas as pd

from tools.change_log import column_diff


def _before() -> pd.DataFrame:
    return pd.DataFrame({"_id": ["a", "b", "c"], "note": [None, None, None], "n": [1, 2, 3]})


def test_a_renamed_column_is_followed_to_its_new_name():
    after = pd.DataFrame({"id": ["a", "b", "c"], "n": [1, 2, 3]})

    rows = column_diff(_before(), after, {"_id": "id"})
    renamed = next(r for r in rows if r["column"].startswith("_id"))

    assert renamed["column"] == "_id -> id"
    assert renamed["nulls after"] == 0
    assert renamed["distinct after"] == 3


def test_a_dropped_column_is_reported_as_removed():
    after = pd.DataFrame({"_id": ["a", "b", "c"], "n": [1, 2, 3]})

    rows = column_diff(_before(), after, {})
    dropped = next(r for r in rows if r["column"] == "note")

    assert dropped["nulls after"] is None
    assert dropped["status"] == "removed"


def test_an_untouched_column_is_reported_as_kept():
    after = _before()

    rows = column_diff(_before(), after, {})

    assert all(row["status"] == "kept" for row in rows)
    assert [row["column"] for row in rows] == ["_id", "note", "n"]


def test_a_column_that_only_exists_afterwards_is_still_listed():
    after = pd.DataFrame({"_id": ["a", "b", "c"], "note": [None] * 3, "n": [1, 2, 3],
                          "derived": [1, 1, 1]})

    rows = column_diff(_before(), after, {})
    added = next(r for r in rows if r["column"] == "derived")

    assert added["status"] == "added"
    assert added["nulls before"] is None


def test_the_counts_describe_the_two_frames():
    after = pd.DataFrame({"_id": ["a", "b", None], "note": [None] * 3, "n": [1, 1, 1]})

    rows = {r["column"]: r for r in column_diff(_before(), after, {})}

    assert rows["_id"]["nulls before"] == 0 and rows["_id"]["nulls after"] == 1
    assert rows["n"]["distinct before"] == 3 and rows["n"]["distinct after"] == 1
