"""Mines arithmetic relations between numeric columns for the Format & Consistency agent, and
reports the rows that break one. cross_column_checks answers a different question: it mines
value-to-value lookups and caps a predictor's cardinality, which excludes a total and its parts by
construction, so a balance contradicting the two counts it is derived from passes every existing
check. A relation is claimed only when it already holds for the great majority of comparable rows,
and only for columns whose values carry magnitude rather than identity, so the minority breaking
it is evidence of a defect instead of an accident of noise. Which side of a broken identity is
wrong is not decided here - the target is reported, and what to do about it belongs to the
approval gate."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from noipa_dq.models import FormatViolation, ValidationReport

_MIN_AGREEMENT = 0.9
_MIN_ROWS = 30
_MIN_DISTINCT = 5
_MAX_NUMERIC_COLUMNS = 16
_TOLERANCE = 0.011
_OPERATORS = {"-": np.subtract, "+": np.add}


@dataclass(frozen=True)
class Identity:
    """A relation of the form target = left <operator> right, with the rows that break it."""
    target: str
    left: str
    operator: str
    right: str
    agreement: float
    breaking_rows: tuple[int, ...]

    def expression(self) -> str:
        return f"{self.left} {self.operator} {self.right}"


def arithmetic_reports(df: pd.DataFrame, min_agreement: float = _MIN_AGREEMENT) -> list[ValidationReport]:
    """One report per column whose mined identity some rows contradict."""
    reports: list[ValidationReport] = []
    for identity in mine_identities(df, min_agreement):
        if not identity.breaking_rows:
            continue
        reports.append(ValidationReport(
            column_name=identity.target,
            violations=[
                FormatViolation(
                    column_name=identity.target,
                    row_index=int(row),
                    value=df.at[row, identity.target],
                    expected_pattern=f"{identity.target} = {identity.expression()}",
                    kind="consistency",
                )
                for row in identity.breaking_rows
            ],
            detected_total=len(identity.breaking_rows),
        ))
    return reports


def mine_identities(df: pd.DataFrame, min_agreement: float = _MIN_AGREEMENT) -> list[Identity]:
    """One identity per set of columns that constrain each other, over columns holding magnitudes.

    A relation between three columns can be written three ways - a balance equals inbound minus
    outbound, and equally inbound equals the balance plus outbound - so mining every target would
    report one defect three times and name all three columns as the offender. The rearrangements
    are collapsed to a single identity, and the column reported is the one written last among the
    three, because an export writes a derived column after the columns it derives from. That is a
    convention rather than a deduction, so the identity names all three columns and which side to
    change stays a decision for the approval gate."""
    numeric = _magnitude_columns(df)
    position = {str(column): index for index, column in enumerate(df.columns)}
    families: dict[frozenset, Identity] = {}
    for target in numeric:
        for left in numeric:
            if left == target:
                continue
            for right in numeric:
                if right in (target, left):
                    continue
                found = _test(numeric, target, left, "-", right, min_agreement)
                if found is None and left < right:
                    found = _test(numeric, target, left, "+", right, min_agreement)
                if found is None:
                    continue
                family = frozenset((target, left, right))
                current = families.get(family)
                if current is None or _prefer(found, current, position):
                    families[family] = found
    return sorted(families.values(), key=lambda i: position.get(i.target, 0))


def _prefer(candidate: Identity, current: Identity, position: dict[str, int]) -> bool:
    """Whether candidate is the better statement of a relation already found in another form."""
    if candidate.agreement != current.agreement:
        return candidate.agreement > current.agreement
    return position.get(candidate.target, 0) > position.get(current.target, 0)


def _test(
    numeric: dict[str, pd.Series], target: str, left: str, operator: str,
    right: str, min_agreement: float,
) -> Identity | None:
    a, b, c = numeric[target], numeric[left], numeric[right]
    comparable = a.notna() & b.notna() & c.notna()
    if int(comparable.sum()) < _MIN_ROWS:
        return None
    expected = _OPERATORS[operator](b[comparable], c[comparable])
    if _degenerate(a[comparable], b[comparable], c[comparable], expected):
        return None
    matches = np.isclose(a[comparable], expected, rtol=1e-9, atol=_TOLERANCE)
    agreement = float(matches.mean())
    if agreement < min_agreement:
        return None
    breaking = a[comparable].index[~matches]
    return Identity(target, left, operator, right, round(agreement, 4),
                    tuple(int(row) for row in breaking))


def _degenerate(a: pd.Series, b: pd.Series, c: pd.Series, expected: pd.Series) -> bool:
    """Whether the relation is arithmetically true but says nothing. A column of zeros makes every
    sum a restatement of its other side, and a target with almost no distinct values agrees with
    too much by chance to be evidence of anything."""
    if a.nunique() < _MIN_DISTINCT or expected.nunique() < _MIN_DISTINCT:
        return True
    if c.nunique() <= 1 or b.nunique() <= 1:
        return True
    return bool(np.isclose(b, c, rtol=1e-9, atol=_TOLERANCE).mean() > _MIN_AGREEMENT)


def _magnitude_columns(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Columns whose values are quantities rather than labels. A datetime, a boolean and anything
    pandas cannot read as a number are excluded; identifiers are not filtered by uniqueness,
    because a continuous amount is just as distinct per row as a key and the agreement threshold
    already makes a spurious relation over a key vanishingly unlikely. The search is capped so a
    wide table cannot make the triple scan expensive."""
    out: dict[str, pd.Series] = {}
    rows = len(df)
    for column in df.columns:
        if len(out) >= _MAX_NUMERIC_COLUMNS:
            break
        series = df[column]
        if pd.api.types.is_datetime64_any_dtype(series) or pd.api.types.is_bool_dtype(series):
            continue
        values = pd.to_numeric(series, errors="coerce")
        populated = int(values.notna().sum())
        if not populated or populated < _MIN_ROWS or populated / max(rows, 1) < 0.5:
            continue
        out[str(column)] = values
    return out
