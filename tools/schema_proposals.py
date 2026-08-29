"""Builds the remediation proposals whose form is already decided by the detection stages: dropping a column that is almost entirely empty, and renaming one whose name breaks the baseline convention. Both are schema decisions that only a person should approve, but neither needs a model to be written down - the column, the operation and the parameter are all known. Generating them deterministically keeps them out of the LLM's hands, where they were previously either ignored or turned into value fixes."""
from __future__ import annotations

from models import FixProposal, Operation, ValidationReport

_SPARSE_PREFIX = "sparse column"
_NAMING_PREFIX = "naming convention"


def schema_proposals(reports: list[ValidationReport], columns: list[str]) -> list[FixProposal]:
    present = set(columns)
    proposals: list[FixProposal] = []
    for report in reports:
        if report.column_name not in present:
            continue
        for violation in report.violations:
            pattern = str(violation.expected_pattern or "")
            if pattern.startswith(_SPARSE_PREFIX):
                proposals.append(_drop_proposal(report.column_name, violation, pattern))
            elif pattern.startswith(_NAMING_PREFIX) and violation.value:
                proposals.append(_rename_proposal(report.column_name, violation, present))
    return [p for p in proposals if p is not None]


def _drop_proposal(column: str, violation, pattern: str) -> FixProposal:
    rate = pattern.split(":", 1)[1].strip() if ":" in pattern else "almost entirely"
    return FixProposal(
        id=f"schema_drop_{column}",
        description=f"Drop '{column}': it is {rate} and carries almost no information.",
        rationale=(
            f"{violation.value} of its cells are empty. Removing the column is a schema "
            "decision, so it is proposed rather than applied."
        ),
        addresses_violations=[f"sparse:{column}"],
        affected_columns=[column],
        estimated_rows_affected=int(violation.value or 0),
        operations=[Operation(kind="drop_column", column=column)],
    )


def _rename_proposal(column: str, violation, present: set[str]) -> FixProposal | None:
    suggested = str(violation.value)
    if not suggested or suggested in present or suggested == column:
        return None
    return FixProposal(
        id=f"schema_rename_{column}",
        description=f"Rename '{column}' to '{suggested}' to match the naming convention.",
        rationale=(
            "The column name breaks the convention declared in the baseline. Renaming "
            "changes the schema, so it is proposed rather than applied."
        ),
        addresses_violations=[f"naming:{column}"],
        affected_columns=[column],
        operations=[Operation(kind="rename_column", column=column, new_name=suggested)],
    )
