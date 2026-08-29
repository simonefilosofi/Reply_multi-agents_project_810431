"""Final reporting node: recomputes the residual violations on the remediated dataset across every category - format, completeness and cross-column consistency - so that the before/after comparison comes from like-for-like measurements, derives the three-point quality metrics and the aggregate reliability score, asks the LLM for the narrative sections, and emits the cleaned dataset, a cell-level audit trail of every change, a structured JSON artefact which preserves the text verbatim, and a PDF, whose core font is latin-1 and therefore receives a transliterated copy. Implements the Report Generator agent."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
from fpdf import FPDF
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import DateFormat, EnumFormat, FormatViolation, RangeFormat, RegexFormat, ValidationReport
from state import PipelineState
from tools.completeness import completeness_report
from tools.cross_column_checks import candidate_predictors, cross_column_reports
from tools.temporal_stability import time_column
from tools.duplicate_rows import duplicate_row_analysis
from tools.operations import describe_operation, operations_as_python
from tools.reliability_score import DIMENSIONS, checked_cells_by_column, compare, compute_metrics, violation_counts
from tools.validate_format import validate_format
from utils.prompts import load_prompt


_SPEC_TYPES = {
    "enum": EnumFormat,
    "regex": RegexFormat,
    "range": RangeFormat,
    "date": DateFormat,
}


class _ReportResponse(BaseModel):
    executive_summary: str
    dataset_overview: str
    quality_findings: str
    actions_taken: str
    recommendations: str


def report_generator_node(state: PipelineState) -> PipelineState:
    residual = _residual_reports(state)
    quality = _quality_section(state, residual)
    payload = _build_payload(state, residual, quality)
    system = load_prompt("report_generator")
    chain = ChatOpenAI(model="gpt-5.4-mini", temperature=0).with_structured_output(_ReportResponse)

    result: _ReportResponse = chain.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ])

    out = _output_path(state)
    _write_artefacts(state, out)
    out.with_suffix(".json").write_text(
        json.dumps({**payload, "narrative": result.model_dump()}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    pdf = _render_pdf(state, result, quality)
    pdf.output(str(out))
    return state.model_copy(update={"quality_snapshots": quality["snapshots"]})


# ── payload ───────────────────────────────────────────────────────────────────

def _residual_reports(state: PipelineState) -> list[ValidationReport]:
    if state.dataset is None:
        return []
    reports: list[ValidationReport] = []
    for column, info in state.inferred_format_specs.items():
        if column not in state.dataset.columns:
            continue
        spec = _spec_from_dict(info.get("final_spec"))
        if spec is None:
            continue
        reports.append(validate_format(column, state.dataset[column], spec))
    reports.extend(_residual_completeness(state))
    reports.extend(_residual_duplicates(state))
    reports.extend(cross_column_reports(
        state.dataset,
        candidate_predictors(state.payload, set(state.dataset.columns), state.dataset),
        clock=time_column(state.dataset, state.inferred_format_specs),
    ))
    return reports


def _changes_summary(change_log: list[dict]) -> dict:
    if not change_log:
        return {"total_cells_changed": 0, "by_column": {}, "by_source": {}}
    frame = pd.DataFrame(change_log)
    return {
        "total_cells_changed": len(frame),
        "by_column": frame["column"].value_counts().to_dict(),
        "by_source": frame["source"].value_counts().to_dict(),
    }


def _residual_duplicates(state: PipelineState) -> list[ValidationReport]:
    analysis = duplicate_row_analysis(state.dataset)
    return [
        ValidationReport(
            column_name=key,
            violations=[FormatViolation(
                column_name=key,
                row_index=-1,
                value=stats["keys_with_conflicting_data"],
                expected_pattern=f"duplicate records: {stats['keys_with_conflicting_data']} keys still collide",
            )],
        )
        for key, stats in analysis["key_collisions"].items()
        if stats["keys_with_conflicting_data"]
    ]


def _residual_completeness(state: PipelineState) -> list[ValidationReport]:
    report = completeness_report(state.dataset)
    entries = [
        ValidationReport(
            column_name=column,
            violations=[FormatViolation(
                column_name=column,
                row_index=-1,
                value=stats["nulls"],
                expected_pattern="missing value",
            )],
        )
        for column, stats in report["by_column"].items()
        if stats["nulls"]
    ]
    return entries


def _spec_from_dict(spec: dict | None):
    if not spec:
        return None
    return _SPEC_TYPES[spec["type"]](**spec) if spec.get("type") in _SPEC_TYPES else None


def _quality_section(state: PipelineState, residual: list[ValidationReport]) -> dict:
    conventions = state.baseline.global_conventions if state.baseline else None
    final = (
        compute_metrics(
            state.dataset,
            residual,
            conventions,
            checked_cells=checked_cells_by_column(state.dataset, state.inferred_format_specs),
            duplicate_analysis=duplicate_row_analysis(state.dataset),
        )
        if state.dataset is not None
        else {}
    )
    snapshots = {**state.quality_snapshots, "final": final}
    scoped_before, scoped_after = _like_for_like_snapshots(
        state, snapshots.get("pre_remediation", {}), residual, conventions
    )
    if scoped_before:
        snapshots["pre_remediation_scoped"] = scoped_before
        snapshots["final_scoped"] = scoped_after
    delivered = compare(snapshots.get("raw") or scoped_before or snapshots.get("detected", {}), final)
    like_for_like = compare(scoped_before, scoped_after) if scoped_before else {}
    return {
        "snapshots": snapshots,
        "as_delivered": delivered,
        "like_for_like": like_for_like,
        "dimensions_compared": delivered["dimensions"],
        "dimensions_excluded": [d for d in DIMENSIONS if d not in delivered["dimensions"]],
        "reliability_before": delivered["before"],
        "reliability_after": delivered["after"],
        "hidden_defects_unmasked": _hidden_defects(snapshots),
    }


def _like_for_like_snapshots(
    state: PipelineState, before: dict, residual: list[ValidationReport], conventions
) -> tuple[dict, dict]:
    """Measures both ends of the run on the same columns: the pre-remediation snapshot restricted
    to the columns that survive, and the remediated dataset restricted to those same columns.
    Scoping only the earlier side would compare a subset against the whole and call the result
    like-for-like."""
    if not before or state.dataset is None:
        return {}, {}
    null_by_column = before.get("null_by_column") or {}
    origins = _origin_columns(state)
    pairs = [(origins.get(str(c), str(c)), str(c)) for c in state.dataset.columns]
    pairs = [(origin, current) for origin, current in pairs if origin in null_by_column]
    if not pairs:
        return {}, {}

    current_names = [current for _, current in pairs]
    sub = state.dataset[current_names]
    after = compute_metrics(
        sub,
        [report for report in residual if report.column_name in set(current_names)],
        conventions,
        checked_cells=checked_cells_by_column(sub, state.inferred_format_specs),
        duplicate_analysis=duplicate_row_analysis(sub),
    )
    return _scope_metrics(before, [origin for origin, _ in pairs]), after


def _scope_metrics(before: dict, kept: list[str]) -> dict:
    null_by_column = before.get("null_by_column") or {}
    rows = before.get("rows", 0)
    cells = rows * len(kept)
    nulls = sum(null_by_column[column] for column in kept)
    selected = set(kept)
    checked = {
        column: count
        for column, count in (before.get("checked_cells_by_column") or {}).items()
        if column in selected
    }
    checked_total = sum(checked.values())
    format_violations = sum(
        count
        for column, count in (before.get("format_violations_by_column") or {}).items()
        if column in selected
    )
    inconsistent = min(
        sum(
            count
            for column, count in (before.get("inconsistent_rows_by_column") or {}).items()
            if column in selected
        ),
        before.get("inconsistent_rows", 0),
    )
    defects = {
        column: labels
        for column, labels in (before.get("structural_defects") or {}).items()
        if column in kept
    }
    return {
        **before,
        "columns": len(kept),
        "columns_compared": len(kept),
        "null_cells": nulls,
        "structural_defects": defects,
        "columns_with_structural_defects": len(defects),
        "columns_badly_named": sum(1 for labels in defects.values() if "naming" in labels),
        "columns_sparse": sum(1 for labels in defects.values() if "sparse" in labels),
        "columns_redundant": sum(1 for labels in defects.values() if "redundant" in labels),
        "checked_cells": checked_total or None,
        "checked_cells_by_column": checked,
        "format_violations": format_violations,
        "inconsistent_rows": inconsistent,
        "completeness": round(max(cells - nulls, 0) / cells, 4) if cells else None,
        "schema_conformity": round((len(kept) - len(defects)) / len(kept), 4),
        "validity": (
            round(max(checked_total - format_violations, 0) / checked_total, 4)
            if checked_total
            else None
        ),
        "consistency": round(max(rows - inconsistent, 0) / rows, 4) if rows else None,
    }


def _origin_columns(state: PipelineState) -> dict[str, str]:
    """Maps a column of the remediated dataset back to the name it carried in the pre-remediation
    snapshot, which is taken after the duplicate-column election and therefore already uses
    canonical names. Only the renames applied by approved fixes happened after that point, so
    only they need inverting; reaching further back, to the column that originally held the
    data, names something the snapshot does not contain and drops the column from the
    comparison."""
    origins: dict[str, str] = {}
    applied = set(state.applied_fix_ids)
    for proposal in state.proposed_fixes:
        if proposal.id not in applied:
            continue
        for operation in proposal.operations:
            if operation.kind == "rename_column" and operation.new_name:
                origins[operation.new_name] = origins.get(operation.column, operation.column)
    return origins


def _violation_count(report: ValidationReport) -> int:
    counts = violation_counts([report])
    return counts["format"] + counts["completeness"] + counts["consistency"] + counts["uniqueness"]


def _hidden_defects(snapshots: dict) -> dict:
    raw, detected = snapshots.get("raw"), snapshots.get("detected")
    if not raw or not detected:
        return {}
    return {
        "disguised_nulls_unmasked": int(detected.get("null_cells", 0) - raw.get("null_cells", 0)),
        "apparent_completeness": raw.get("completeness"),
        "true_completeness": detected.get("completeness"),
    }


def _build_payload(state: PipelineState, residual: list[ValidationReport], quality: dict) -> dict:
    shape = {}
    null_summary = []
    if state.dataset is not None:
        df = state.dataset
        shape = {"rows": len(df), "columns": len(df.columns)}
        null_pct = df.isnull().mean().mul(100).round(1)
        null_summary = [
            {"column": col, "null_pct": pct}
            for col, pct in null_pct.items()
            if pct > 0
        ]

    return {
        "dataset_path": state.dataset_path,
        "detected_domain": state.detected_domain,
        "detected_language": state.detected_language,
        "shape": shape,
        "null_summary": null_summary,
        "semantic_payload": [
            {
                "column_name": p.column_name,
                "meaning": p.description,
                "dtype": p.dtype,
                "placeholders_found": p.placeholders,
            }
            for p in state.payload
        ],
        "duplicate_resolutions": [
            {
                "group": r.group,
                "survivor": r.data_survivor,
                "canonical_name": r.canonical_name,
                "dropped": r.dropped,
                "rationale": r.rationale,
                "cells_backfilled": r.cells_backfilled,
                "cells_overwritten": r.cells_overwritten,
                "values_lost": r.values_lost,
            }
            for r in state.duplicate_resolutions
        ],
        "duplicate_rows": state.duplicate_rows,
        "auto_remediations": state.auto_remediations,
        "changes_summary": _changes_summary(state.change_log),
        "format_violations_detected": [
            {"column_name": r.column_name, "violation_count": _violation_count(r)}
            for r in state.validation_reports
            if r.violations
        ],
        "format_violations_residual": [
            {"column_name": r.column_name, "violation_count": _violation_count(r)}
            for r in residual
            if r.violations
        ],
        "completeness": state.completeness,
        "violations_by_kind_detected": violation_counts(state.validation_reports),
        "violations_by_kind_residual": violation_counts(residual),
        "naming_violations": [
            {"column_name": r.column_name, "suggested_name": v.value}
            for r in state.validation_reports
            for v in r.violations
            if str(v.expected_pattern or "").startswith("naming convention")
        ],
        "anomalies": [
            {
                "column_name": a.column_name,
                "method": a.method,
                "detected": int(a.stats.get("detected", len(a.anomalies))),
                "sampled": int(a.stats.get("sampled", len(a.anomalies))),
                "comment": a.comment,
                "examples": [e.value for e in a.anomalies[:5]],
            }
            for a in state.anomaly_reports
        ],
        "proposed_remediations": [
            {
                "id": p.id,
                "description": p.description,
                "rationale": p.rationale,
                "affected_columns": p.affected_columns,
                "estimated_rows_affected": p.estimated_rows_affected,
                "operations": [describe_operation(o) for o in p.operations],
                "equivalent_python": operations_as_python(p.operations),
                "applied": p.id in state.applied_fix_ids,
            }
            for p in state.proposed_fixes
        ],
        "applied_fix_ids": state.applied_fix_ids,
        "value_corrections": {
            col: {k: v for k, v in list(mapping.items())[:20]}
            for col, mapping in state.value_corrections.items()
        },
        "quality": quality,
        "surviving_columns": state.surviving_columns,
        "errors": state.errors,
    }


# ── pdf renderer ──────────────────────────────────────────────────────────────

def _write_artefacts(state: PipelineState, out: Path) -> None:
    if state.dataset is not None:
        suffix = ".cleaned.csv" if state.applied_fix_ids else ".processed.csv"
        state.dataset.to_csv(out.with_suffix(suffix), index=False)
    if state.change_log:
        pd.DataFrame(state.change_log).to_csv(out.with_suffix(".changes.csv"), index=False)


def _output_path(state: PipelineState) -> Path:
    if state.dataset_path:
        return Path(state.dataset_path).with_suffix(".pdf")
    return Path("report.pdf")


_PDF_SUBSTITUTIONS = {
    "\u20ac": "EUR",
    "\u2019": "'",
    "\u2018": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u2026": "...",
}


def _pdf_safe(text: str) -> str:
    for source, target in _PDF_SUBSTITUTIONS.items():
        text = text.replace(source, target)
    return text.encode("latin-1", "replace").decode("latin-1")


def _section(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(0, 8, _pdf_safe(title), new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.ln(3)


def _body(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, _pdf_safe(text))
    pdf.ln(4)


def _render_pdf(state: PipelineState, report: _ReportResponse, quality: dict) -> FPDF:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Data Quality Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _pdf_safe(f"Dataset   : {state.dataset_path or 'N/A'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, _pdf_safe(f"Domain    : {state.detected_domain or 'N/A'}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    _section(pdf, "Reliability Score")
    _body(pdf, _score_text(quality))

    _section(pdf, "Executive Summary")
    _body(pdf, report.executive_summary)

    _section(pdf, "Dataset Overview")
    _body(pdf, report.dataset_overview)

    _section(pdf, "Quality Findings")
    _body(pdf, report.quality_findings)

    _section(pdf, "Actions Taken")
    _body(pdf, report.actions_taken)

    _section(pdf, "Recommendations")
    _body(pdf, report.recommendations)

    return pdf


_COUNTERS = (
    ("rows", "rows"),
    ("columns", "columns"),
    ("null cells", "null_cells"),
    ("cells checked", "checked_cells"),
    ("format violations", "format_violations"),
    ("inconsistent rows", "inconsistent_rows"),
    ("duplicate rows", "duplicate_rows"),
    ("rows in key conflict", "rows_in_key_conflict"),
    ("columns badly named", "columns_badly_named"),
    ("columns almost empty", "columns_sparse"),
    ("columns duplicating another", "columns_redundant"),
)


def _comparison_block(comparison: dict, before_label: str, after_label: str, note: str) -> list[str]:
    before, after = comparison["before"], comparison["after"]
    lines = [
        f"{before_label:38}: {_fmt(before.get('score'))}",
        f"{after_label:38}: {_fmt(after.get('score'))}",
        note,
    ]
    for key in comparison["dimensions"]:
        lines.append(
            f"  {key:20} {_fmt(before.get('components', {}).get(key))} -> "
            f"{_fmt(after.get('components', {}).get(key))}"
            f"   w={before.get('weights', {}).get(key, 0):g}"
        )
    return lines


def _score_text(quality: dict) -> str:
    snapshots = quality.get("snapshots") or {}
    scoped = snapshots.get("pre_remediation_scoped") or {}
    after_metrics = snapshots.get("final") or {}

    lines = _comparison_block(
        quality["as_delivered"],
        "Reliability of the file as delivered",
        "Reliability after remediation",
        "Geometric mean over the dimensions measurable at both ends without a validation pass, "
        "so that the file as received can be scored at all. A single broken dimension pulls the "
        "whole score down rather than being averaged away.",
    )

    like_for_like = quality.get("like_for_like") or {}
    if like_for_like.get("dimensions"):
        lines += [""] + _comparison_block(
            like_for_like,
            "Like-for-like before remediation",
            "Like-for-like after remediation",
            f"Restricted to the {scoped.get('columns_compared', 0)} columns present at both ends "
            "and extended with the dimensions that need a validation pass, so that removing a "
            "redundant or empty column is not read as an improvement.",
        )

    excluded = quality.get("dimensions_excluded") or []
    if excluded:
        lines += ["", "Excluded from the headline score, not measurable on the raw file: "
                  + ", ".join(excluded)]

    delivered_metrics = snapshots.get("raw") or scoped
    lines += ["", "Counters behind the headline pair (as delivered -> after remediation):"]
    for label, key in _COUNTERS:
        lines.append(
            f"  {label:28} {_count(delivered_metrics.get(key))} -> {_count(after_metrics.get(key))}"
        )

    scoped_after = snapshots.get("final_scoped") or {}
    if scoped and scoped_after:
        lines += [
            "",
            f"Counters behind the like-for-like pair, on the "
            f"{scoped.get('columns_compared', 0)} comparable columns (before -> after):",
        ]
        for label, key in _COUNTERS:
            lines.append(
                f"  {label:28} {_count(scoped.get(key))} -> {_count(scoped_after.get(key))}"
            )

    lines += [
        "",
        "Validity divides by the cells actually checked against a format specification, not by "
        "every cell in the table. Schema conformity is the share of columns carrying no "
        "structural fault: a name breaking the convention, a column too empty to inform, or a "
        "column merely repeating another.",
        "",
        "Detected anomalies are reported in the findings but deliberately excluded from this "
        "score: a statistical outlier is unusual, which is not the same as wrong.",
    ]

    hidden = quality.get("hidden_defects_unmasked") or {}
    if hidden:
        lines += [
            "",
            f"Disguised nulls unmasked by the pipeline: {hidden.get('disguised_nulls_unmasked')}",
            f"Apparent completeness of the raw file  : {_fmt(hidden.get('apparent_completeness'))}",
            f"True completeness once unmasked        : {_fmt(hidden.get('true_completeness'))}",
        ]
    return "\n".join(lines)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def _count(value: int | None) -> str:
    return "n/a" if value is None else f"{value:,}"
