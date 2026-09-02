"""Pins the one notion of dtype agreement the pipeline has. A declaration reaches a column in one
of two vocabularies - the canonical catalogue's (integer, float, string) or pandas' own - while
the caster deliberately lands every integer on the nullable Int64, so the declared and the
realised dtype are almost never spelled alike. Comparing them as strings marked four correctly
cast columns of attivazioniCessazioni untyped and cost that run 0.13 of its reliability score.
These tests hold the families together and hold the reported defects to the defects that were
actually scored."""
from __future__ import annotations

import pandas as pd
import pytest

import noipa_dq.tools.reliability_score as rs
from noipa_dq.models import GlobalConventions
from noipa_dq.tools.safe_cast import dtype_family, dtype_satisfied


@pytest.mark.parametrize(("declared", "realised"), [
    ("integer", "Int64"),
    ("int64", "Int64"),
    ("int64", "int64"),
    ("float", "Int64"),
    ("float", "float64"),
    ("float64", "float64"),
    ("string", "string"),
    ("object", "object"),
    ("object", "string"),
    ("string", "object"),
    ("datetime64[ns]", "datetime64[ns]"),
    ("bool", "boolean"),
])
def test_a_realised_dtype_meets_a_declaration_written_in_either_vocabulary(
    declared: str, realised: str
) -> None:
    assert dtype_satisfied(declared, realised)


@pytest.mark.parametrize(("declared", "realised"), [
    ("int64", "object"),
    ("integer", "object"),
    ("integer", "float64"),
    ("float", "object"),
    ("datetime64[ns]", "object"),
    ("string", "Int64"),
])
def test_a_column_that_never_took_the_declared_type_is_not_satisfied(
    declared: str, realised: str
) -> None:
    assert not dtype_satisfied(declared, realised)


def test_a_float_declaration_is_met_by_an_integer_because_the_caster_promotes_it() -> None:
    """safe_cast turns a float declaration into an integer one when no value carries a decimal
    part, so the realised column is the caster obeying the declaration, not defying it."""
    assert dtype_satisfied("float", "Int64")
    assert not dtype_satisfied("integer", "float64")


@pytest.mark.parametrize(("dtype", "family"), [
    ("integer", "integer"), ("int64", "integer"), ("Int64", "integer"),
    ("float", "float"), ("float64", "float"), ("decimal", "float"),
    ("string", "string"), ("object", "string"),
    ("datetime64[ns]", "datetime"), ("bool", "boolean"), ("category", "category"),
])
def test_both_vocabularies_reduce_to_the_family_the_caster_would_produce(
    dtype: str, family: str
) -> None:
    assert dtype_family(dtype) == family


def test_an_integer_column_cast_to_the_nullable_type_is_not_a_defect() -> None:
    df = pd.DataFrame({"mese": pd.array([1, 2, None], dtype="Int64")})
    metrics = rs.compute_metrics(
        df, conventions=GlobalConventions(), declared_dtypes={"mese": "int64"}
    )
    assert metrics["schema_conformity"] == 1.0
    assert metrics["structural_defects"] == {}


def test_a_column_matched_to_the_catalogue_is_not_a_defect_for_saying_integer() -> None:
    """A canonical match declares the catalogue's word. Penalising it made matching the registry
    lower the score, which inverts what the match is for."""
    df = pd.DataFrame({"anno": pd.array([2024, 2025], dtype="Int64")})
    metrics = rs.compute_metrics(
        df, conventions=GlobalConventions(), declared_dtypes={"anno": "integer"}
    )
    assert metrics["schema_conformity"] == 1.0


def test_the_reported_defects_are_the_defects_that_were_scored() -> None:
    """The score counted untyped columns while the reported defect set was built without the
    declarations, so a run could report no defects and still be marked down for four."""
    df = pd.DataFrame({"codice": ["A", "B"]})
    metrics = rs.compute_metrics(
        df, conventions=GlobalConventions(), declared_dtypes={"codice": "int64"}
    )
    assert metrics["structural_defects"] == {"codice": ["untyped"]}
    assert metrics["columns_with_structural_defects"] == 1
    assert metrics["columns_untyped"] == 1
    assert metrics["schema_conformity"] == 0.0


def test_a_column_with_no_declaration_is_never_untyped() -> None:
    df = pd.DataFrame({"codice": ["A", "B"], "importo": [1.5, 2.5]})
    metrics = rs.compute_metrics(df, conventions=GlobalConventions())
    assert metrics["schema_conformity"] == 1.0
    assert metrics["columns_untyped"] == 0
