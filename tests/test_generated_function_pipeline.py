"""Pins the path a generated cleaning function takes once the Unified agent has proposed one: the dry run that measures it, the post-fix invariants that can still reject it, and the executor that applies it and records the cells it changed. The function here stands in for the model's output, so the integration is covered without an LLM call."""
from __future__ import annotations

import pandas as pd

from noipa_dq.models import DateFormat, FixProposal, FormatViolation, Operation, ValidationReport
from noipa_dq.tools.execute_fixes import execute_fixes
from noipa_dq.tools.trial_execute import trial_execute

_SOURCE = """
def clean_value(value):
    import re
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\\d{6}", text):
        return text
    match = re.fullmatch(r"([A-Za-z]{3})-(\\d{4})", text)
    if match is None:
        return None
    months = {"gen": "01", "mar": "03", "giu": "06", "lug": "07", "set": "09"}
    month = months.get(match.group(1).lower())
    return match.group(2) + month if month else None
"""

_DESTRUCTIVE_SOURCE = """
def clean_value(value):
    return None
"""

_SPEC = DateFormat(strftime_pattern="%Y%m")


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"rata": ["202401", "MAR-2024", "LUG-2024", "202405", "GIU-2024"]})


def _proposal(source: str) -> FixProposal:
    return FixProposal(
        id="f1",
        description="Normalise rata to YYYYMM.",
        rationale="The column is a period.",
        affected_columns=["rata"],
        operations=[Operation(kind="apply_generated_function", column="rata", source=source)],
    )


def _reports() -> dict[str, ValidationReport]:
    return {"rata": ValidationReport(column_name="rata", violations=[
        FormatViolation(
            column_name="rata", row_index=index, value=value,
            expected_pattern="date: %Y%m", kind="format",
        )
        for index, value in ((1, "MAR-2024"), (2, "LUG-2024"), (4, "GIU-2024"))
    ])}


def test_the_dry_run_reports_the_violations_the_function_removes() -> None:
    trial = trial_execute(
        _frame(), _proposal(_SOURCE), {}, {"rata": _SPEC}, _reports(),
    )

    assert trial["status"] == "applied"
    assert trial["invariant_violations"] == []
    assert trial["rows_changed"] == 3
    assert trial["violation_delta"]["rata"]["format_violations_before"] == 3
    assert trial["violation_delta"]["rata"]["format_violations_after"] == 0


def test_a_function_that_empties_the_column_is_rejected_by_the_invariants() -> None:
    trial = trial_execute(
        _frame(), _proposal(_DESTRUCTIVE_SOURCE), {}, {"rata": _SPEC}, _reports(),
    )

    assert trial["invariant_violations"]
    assert "were deleted" in trial["invariant_violations"][0]


def test_the_executor_applies_the_function_and_logs_the_cells() -> None:
    cleaned, statuses = execute_fixes(_frame(), [_proposal(_SOURCE)])

    assert statuses[0]["status"] == "applied"
    assert cleaned["rata"].tolist() == ["202401", "202403", "202407", "202405", "202406"]
    assert statuses[0]["cells_changed"] == 3
    assert len(cleaned) == len(_frame())


def test_the_executor_refuses_a_function_the_static_gate_rejects() -> None:
    hostile = "def clean_value(value):\n    import os\n    return os.getcwd()"

    cleaned, statuses = execute_fixes(_frame(), [_proposal(hostile)])

    assert statuses[0]["status"] == "error"
    assert "not available to a generated cleaner" in statuses[0]["error"]
    assert cleaned["rata"].tolist() == _frame()["rata"].tolist()
