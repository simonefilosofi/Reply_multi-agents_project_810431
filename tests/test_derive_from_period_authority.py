"""Covers which rows the period-derivation is allowed to rewrite. A period key states its own
year and month, so filling a target that cannot be read as one is arithmetic. Overwriting a
target that is itself well formed is not: it decides that the period is the more trustworthy of
two disagreeing columns, which is a judgement the approval gate owns. These tests pin the
boundary between the two."""
from __future__ import annotations

import pandas as pd

from tools.derive_from_period import contested_rows, derivable_columns, derive


def frame(periods, months, years) -> pd.DataFrame:
    return pd.DataFrame({"rata": periods, "mese": months, "anno": years})


def agreeing(n: int = 40) -> dict:
    periods = [f"2024{(i % 12) + 1:02d}" for i in range(n)]
    return {"periods": periods,
            "months": [(i % 12) + 1 for i in range(n)],
            "years": [2024] * n}


def test_malformed_month_is_derived_from_the_period():
    base = agreeing()
    base["months"][3] = "Settembre"
    base["months"][7] = "mese 2"
    df = frame(base["periods"], base["months"], base["years"])

    corrected = derive(df, "rata", "mese", "month")

    assert corrected.iloc[3] == "4"
    assert corrected.iloc[7] == "8"


def test_well_formed_month_disagreeing_with_the_period_is_left_alone():
    base = agreeing()
    base["months"][5] = 11
    df = frame(base["periods"], base["months"], base["years"])

    corrected = derive(df, "rata", "mese", "month")

    assert int(corrected.iloc[5]) == 11


def test_a_disagreement_between_two_well_formed_values_is_reported_instead():
    base = agreeing()
    base["months"][5] = 11
    base["months"][9] = 1
    df = frame(base["periods"], base["months"], base["years"])

    contested = contested_rows(df, "rata", "mese", "month")

    assert set(contested) == {5, 9}


def test_a_malformed_target_is_not_reported_as_contested():
    base = agreeing()
    base["months"][2] = "Dicembre"
    df = frame(base["periods"], base["months"], base["years"])

    assert list(contested_rows(df, "rata", "mese", "month")) == []


def test_a_two_digit_year_is_ambiguous_and_therefore_derived():
    base = agreeing()
    base["years"][4] = "24"
    df = frame(base["periods"], base["months"], base["years"])

    corrected = derive(df, "rata", "anno", "year")

    assert corrected.iloc[4] == "2024"
    assert list(contested_rows(df, "rata", "anno", "year")) == []


def test_a_well_formed_year_disagreeing_with_the_period_is_left_alone():
    base = agreeing()
    base["years"][6] = 2021
    df = frame(base["periods"], base["months"], base["years"])

    corrected = derive(df, "rata", "anno", "year")

    assert int(corrected.iloc[6]) == 2021
    assert list(contested_rows(df, "rata", "anno", "year")) == [6]


def test_rows_whose_period_is_not_canonical_are_untouched():
    base = agreeing()
    base["periods"][8] = "LUG-2024"
    base["months"][8] = "Gennaio"
    df = frame(base["periods"], base["months"], base["years"])

    corrected = derive(df, "rata", "mese", "month")

    assert corrected.iloc[8] == "Gennaio"
    assert 8 not in set(contested_rows(df, "rata", "mese", "month"))


def test_recognition_still_identifies_the_year_and_month_columns():
    base = agreeing()
    df = frame(base["periods"], base["months"], base["years"])

    assert derivable_columns(df, "rata") == {"mese": "month", "anno": "year"}
