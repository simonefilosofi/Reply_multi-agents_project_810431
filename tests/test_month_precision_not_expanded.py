"""Pins that a column stating only a year and a month is not turned into a full date. A period
written as 2024-04 names no day, but pandas resolves it to 2024-04-01, so declaring such a column
a date silently wrote a first-of-the-month into every row: 11,657 cells of a value the file never
contained. The pipeline already treats a month-precision column as a period elsewhere, so the cast
is refused and the values are left for the period handling rather than being given a day they do
not have."""
from __future__ import annotations

import pandas as pd

from noipa_dq.tools.safe_cast import safe_cast


def test_a_year_month_column_is_not_given_a_day():
    series = pd.Series(["2024-04", "2024-11", "2023-02"] * 10)

    cast, blocking = safe_cast(series, "datetime64[ns]")

    assert list(cast) == list(series)
    assert blocking == []


def test_a_compact_period_is_not_given_a_day():
    series = pd.Series(["202404", "202411", "202302"] * 10)

    cast, _ = safe_cast(series, "datetime64[ns]")

    assert list(cast) == list(series)


def test_a_month_before_year_layout_is_not_given_a_day():
    series = pd.Series(["04/2024", "11/2024", "02/2023"] * 10)

    cast, _ = safe_cast(series, "datetime64[ns]")

    assert list(cast) == list(series)


def test_a_full_date_column_is_still_cast():
    series = pd.Series(["2024-04-11", "2024-11-03", "2023-02-27"] * 10)

    cast, blocking = safe_cast(series, "datetime64[ns]")

    assert pd.api.types.is_datetime64_any_dtype(cast)
    assert blocking == []


def test_a_timestamp_column_is_still_cast():
    series = pd.Series(["2024-03-11T02:01:04.421", "2024-07-11T03:01:16.866"] * 15)

    cast, _ = safe_cast(series, "datetime64[ns]")

    assert pd.api.types.is_datetime64_any_dtype(cast)


def test_a_column_where_some_rows_carry_a_day_is_still_cast():
    series = pd.Series(["2024-04", "2024-11-03", "2023-02-27"] * 10)

    cast, _ = safe_cast(series, "datetime64[ns]")

    assert pd.api.types.is_datetime64_any_dtype(cast)


def test_nulls_do_not_make_a_month_column_look_like_a_date():
    series = pd.Series(["2024-04", None, "2024-11", None] * 10)

    cast, _ = safe_cast(series, "datetime64[ns]")

    assert list(cast.dropna()) == list(series.dropna())


def test_a_non_date_target_is_unaffected():
    series = pd.Series(["1", "2", "3"] * 10)

    cast, _ = safe_cast(series, "int64")

    assert list(cast) == [1, 2, 3] * 10
