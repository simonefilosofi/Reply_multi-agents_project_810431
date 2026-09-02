"""Final acceptance check over the two client datasets. Confirms the run completed, every artefact
the contract names was written, the report is internally consistent, and every coverage area in
the report's fault table reported something rather than a zero. Complements tests/acceptance/verify.py, which pins value-level invariants: this
asks whether what reaches the client is complete and says the same thing twice. It reads only a
recorded run under reports/runs/, so it needs no network and no key.

    python tests/acceptance/acceptance.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

DATASETS = {
    "spesa": ROOT / "reports/runs/spesa",
    "attivazioniCessazioni": ROOT / "reports/runs/attivazioniCessazioni",
}
REQUIRED_SECTIONS = (
    "## Verdict",
    "## The dataset as received",
    "### What was wrong, by coverage area",
    "### Schema validation",
    "### Completeness",
    "### Consistency",
    "### Anomaly detection",
    "### Remediation",
    "## What was changed",
    "## The dataset as delivered",
    "## Every column at a glance",
    "## Recommendations",
)
COVERAGE_AREAS = ("Schema validation", "Completeness", "Consistency",
                  "Duplicate detection", "Anomaly detection", "Format validity")


def check(name: str, run: Path) -> list[str]:
    failures: list[str] = []
    payload_path = (run / name).with_suffix(".json")
    if not payload_path.exists():
        return [f"{name}: no report written, so the run never reached the report node"]
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    if payload["errors"]:
        failures.append(f"{name}: finished with errors {payload['errors']}")

    stem = run / name
    for suffix in (".md", ".html", ".pdf", ".json"):
        artefact = stem.with_suffix(suffix)
        if not artefact.exists() or artefact.stat().st_size == 0:
            failures.append(f"{name}: missing or empty artefact {artefact.name}")
    for extra in (f"{name}.cleaned.csv", f"{name}.changes.csv"):
        if not (run / extra).exists():
            failures.append(f"{name}: missing {extra}")

    report = stem.with_suffix(".md")
    text = report.read_text(encoding="utf-8") if report.exists() else ""
    for section in REQUIRED_SECTIONS:
        if section not in text:
            failures.append(f"{name}: report is missing the section {section!r}")

    for area in COVERAGE_AREAS:
        row = re.search(rf"^\| {re.escape(area)} \| (.+?) \|", text, re.M)
        if not row:
            failures.append(f"{name}: coverage area {area!r} absent from the fault table")
        elif re.fullmatch(r"(0|no|none)[^|]*", row.group(1).strip(), re.I):
            failures.append(f"{name}: coverage area {area!r} reported nothing ({row.group(1)})")

    failures.extend(_consistency_of(name, text, payload))
    failures.extend(_delivered_matches(name, run, payload))
    return failures


def _consistency_of(name: str, text: str, payload: dict) -> list[str]:
    """The document must not state one figure in a table and a different one in a sentence."""
    failures: list[str] = []
    groups = len(payload["duplicate_resolutions"])
    stated = re.search(r"\| columns duplicating another \| ([\d,]+) \|", text)
    if stated and int(stated.group(1).replace(",", "")) != groups:
        failures.append(
            f"{name}: summary says {stated.group(1)} duplicated columns, "
            f"the run resolved {groups} groups"
        )
    if re.search(r"\b1 duplicate column groups\b", text):
        failures.append(f"{name}: a single duplicate group is described in the plural")

    delivered = re.search(r"\| duplicate rows \| ([\d,]+) \|", text)
    removed = (payload.get("duplicate_rows") or {}).get("rows_removed")
    if delivered and removed is not None:
        if int(delivered.group(1).replace(",", "")) != removed and "not a discrepancy" not in text:
            failures.append(
                f"{name}: the report states {delivered.group(1)} duplicate rows and removed "
                f"{removed} without reconciling them"
            )
    return failures


def _delivered_matches(name: str, run: Path, payload: dict) -> list[str]:
    """The per-column appendix describes the delivered file, so it must match that file."""
    failures: list[str] = []
    final = run / f"{name}.cleaned.csv"
    if not final.exists():
        return [f"{name}: no cleaned dataset written"]
    df = pd.read_csv(final)
    text = (run / name).with_suffix(".md").read_text(encoding="utf-8")
    listed = set(re.findall(r"^\| `([^`]+)`(?:<br>)?[^|]*\| \w", text, re.M))
    missing = set(df.columns) - listed
    if missing:
        failures.append(f"{name}: columns absent from the appendix: {sorted(missing)}")

    for column in df.columns:
        row = re.search(rf"^\| `{re.escape(str(column))}`[^|]*\|[^|]*\| ([\d.]+)% \|", text, re.M)
        if not row:
            continue
        stated = float(row.group(1))
        actual = round(float(df[column].notna().mean()) * 100, 1)
        if abs(stated - actual) > 0.15:
            failures.append(
                f"{name}: appendix says {column} is {stated}% filled, the delivered file is {actual}%"
            )
    return failures


def main() -> int:
    all_failures: list[str] = []
    for name, run in DATASETS.items():
        failures = check(name, run)
        status = "PASS" if not failures else f"FAIL ({len(failures)})"
        print(f"{name:24s} {status}")
        for failure in failures:
            print(f"    - {failure}")
        all_failures.extend(failures)
    print()
    print("ACCEPTANCE PASSED" if not all_failures
          else f"ACCEPTANCE FAILED: {len(all_failures)} problems")
    return 0 if not all_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
