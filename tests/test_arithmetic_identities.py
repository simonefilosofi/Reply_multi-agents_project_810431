"""Covers the mining of arithmetic relations between numeric columns. cross_column_checks caps a
predictor at 0.2 cardinality because it mines value-to-value lookups, which structurally excludes
a total and its parts: `saldo` is determined by `trasferimenti_in` and `trasferimenti_out` by
arithmetic, not by a mapping. Runs over four datasets left 932 such contradictions entirely
undetected. An identity is claimed only when it already holds for the great majority of rows, so
the minority that breaks it is reported rather than the relation being invented from noise."""
from __future__ import annotations

import numpy as np
import pandas as pd

from tools.arithmetic_identities import arithmetic_reports, mine_identities


def ledger(rows: int = 200, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    incoming = rng.integers(0, 400, rows)
    outgoing = rng.integers(0, 400, rows)
    return pd.DataFrame({
        "trasferimenti_in": incoming,
        "trasferimenti_out": outgoing,
        "saldo": incoming - outgoing,
        "comparto": [f"c{i % 6}" for i in range(rows)],
    })


def test_a_difference_identity_is_mined():
    found = mine_identities(ledger())

    assert [(i.target, i.left, i.operator, i.right) for i in found] == [
        ("saldo", "trasferimenti_in", "-", "trasferimenti_out")
    ]


def test_the_rows_breaking_the_identity_are_reported():
    frame = ledger()
    frame.loc[[3, 17, 42], "saldo"] = 999

    reports = arithmetic_reports(frame)

    assert len(reports) == 1
    assert reports[0].column_name == "saldo"
    assert sorted(v.row_index for v in reports[0].violations) == [3, 17, 42]
    assert {v.kind for v in reports[0].violations} == {"consistency"}


def test_the_violation_names_the_identity_it_breaks():
    frame = ledger()
    frame.loc[[5], "saldo"] = -1

    reports = arithmetic_reports(frame)

    assert "trasferimenti_in - trasferimenti_out" in reports[0].violations[0].expected_pattern


def test_a_sum_identity_is_mined():
    rows = 200
    rng = np.random.default_rng(3)
    left, right = rng.integers(0, 500, rows), rng.integers(0, 500, rows)
    frame = pd.DataFrame({"imponibile": left, "contributo": right, "totale": left + right})
    frame.loc[[8, 9], "totale"] = 0

    reports = arithmetic_reports(frame)

    assert [r.column_name for r in reports] == ["totale"]
    assert sorted(v.row_index for v in reports[0].violations) == [8, 9]


def test_an_identity_that_always_holds_produces_no_violations():
    assert arithmetic_reports(ledger()) == []


def test_unrelated_numeric_columns_produce_no_identity():
    rng = np.random.default_rng(11)
    frame = pd.DataFrame({
        "numero_deleghe": rng.integers(1, 900, 300),
        "importo": np.round(rng.uniform(100, 9000, 300), 2),
        "anno": rng.choice([2023, 2024], 300),
    })

    assert mine_identities(frame) == []


def test_a_column_of_zeros_does_not_create_a_trivial_identity():
    rows = 150
    rng = np.random.default_rng(5)
    values = rng.integers(1, 100, rows)
    frame = pd.DataFrame({"a": values, "b": values, "zero": np.zeros(rows, dtype=int)})

    assert mine_identities(frame) == []


def test_a_relation_too_weak_to_be_a_rule_is_not_claimed():
    rows = 200
    rng = np.random.default_rng(13)
    incoming, outgoing = rng.integers(0, 400, rows), rng.integers(0, 400, rows)
    frame = pd.DataFrame({"a": incoming, "b": outgoing, "c": incoming - outgoing})
    frame.loc[frame.index[:120], "c"] = rng.integers(0, 400, 120)

    assert mine_identities(frame) == []


def test_money_is_compared_with_a_tolerance_not_exactly():
    rows = 120
    rng = np.random.default_rng(17)
    gross = np.round(rng.uniform(1000, 9000, rows), 2)
    paid = np.round(gross * 0.98, 2)
    frame = pd.DataFrame({"ritenuto": gross, "versato": paid,
                          "differenza": np.round(gross - paid, 2)})
    frame["differenza"] = frame["differenza"] + 1e-10

    assert [i.target for i in mine_identities(frame)] == ["differenza"]
    assert arithmetic_reports(frame) == []


def test_text_and_date_columns_are_ignored():
    frame = ledger()
    frame["data"] = pd.date_range("2024-01-01", periods=len(frame)).astype(str)

    assert [i.target for i in mine_identities(frame)] == ["saldo"]
