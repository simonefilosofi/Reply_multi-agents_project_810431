"""Final reporting node: recomputes the residual violations on the remediated dataset across every category - format, completeness and cross-column consistency - so that the before/after comparison comes from like-for-like measurements, derives the three-point quality metrics and the aggregate reliability score, asks the LLM for the narrative sections, and emits both a structured JSON artefact, which preserves the text verbatim, and a PDF, whose core font is latin-1 and therefore receives a transliterated copy. Implements the Report Generator agent."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from models import DateFormat, EnumFormat, FormatViolation, RangeFormat, RegexFormat, ValidationReport
from state import PipelineState
from tools.completeness import completeness_report
from tools.cross_column_checks import candidate_predictors, cross_column_reports
from tools.duplicate_rows import duplicate_row_analysis
from tools.reliability_score import compute_metrics, reliability_score, violation_counts
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
        state.dataset, candidate_predictors(state.payload, set(state.dataset.columns), state.dataset)
    ))
    return reports


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
    final = compute_metrics(state.dataset, residual, conventions) if state.dataset is not None else {}
    snapshots = {**state.quality_snapshots, "final": final}
    detected = snapshots.get("detected", {})
    comparable = _comparable_detected(state, detected)
    if comparable:
        comparable = {
            **comparable,
            "format_violations": _count_violations(state.validation_reports),
            "validity": _validity(comparable, state.validation_reports),
        }
        snapshots["detected_comparable"] = comparable
    return {
        "snapshots": snapshots,
        "reliability_before": reliability_score(comparable or detected),
        "reliability_after": reliability_score(final),
        "hidden_defects_unmasked": _hidden_defects(snapshots),
    }


def _comparable_detected(state: PipelineState, detected: dict) -> dict:
    if not detected or state.dataset is None:
        return detected
    null_by_column = detected.get("null_by_column") or {}
    origin = _origin_columns(state)
    kept = [origin.get(str(c), str(c)) for c in state.dataset.columns]
    kept = [c for c in kept if c in null_by_column]
    if not kept:
        return detected
    rows = detected.get("rows", 0)
    cells = rows * len(kept)
    nulls = sum(null_by_column[c] for c in kept)
    return {
        **detected,
        "columns_compared": len(kept),
        "null_cells": nulls,
        "completeness": round(max(cells - nulls, 0) / cells, 4) if cells else None,
    }


def _origin_columns(state: PipelineState) -> dict[str, str]:
    return {r.canonical_name: r.data_survivor for r in state.duplicate_resolutions}


_AGGREGATED_PATTERNS = ("not nullable", "missing value")


def _violation_count(report: ValidationReport) -> int:
    total = 0
    for violation in report.violations:
        if violation.expected_pattern in _AGGREGATED_PATTERNS:
            total += int(violation.value) if str(violation.value).isdigit() else 1
        elif not str(violation.expected_pattern or "").startswith(("naming convention", "sparse column")):
            total += 1
    return total


def _count_violations(reports: list[ValidationReport]) -> int:
    return sum(
        1
        for report in reports
        for violation in report.violations
        if violation.expected_pattern not in ("not nullable", "missing value")
        and not str(violation.expected_pattern or "").startswith(("naming convention", "sparse column"))
    )


def _validity(metrics: dict, reports: list[ValidationReport]) -> float | None:
    cells = metrics.get("rows", 0) * metrics.get("columns", 0)
    if not cells:
        return None
    return round(max(cells - _count_violations(reports), 0) / cells, 4)


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
                "detected": int(a.stats.get("outlier_count") or a.stats.get("rare_values_count") or len(a.anomalies)),
                "sampled": len(a.anomalies),
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


def _score_text(quality: dict) -> str:
    before, after = quality["reliability_before"], quality["reliability_after"]
    lines = [
        f"Reliability score before remediation : {_fmt(before.get('score'))}",
        f"Reliability score after remediation  : {_fmt(after.get('score'))}",
        "",
        "Components (before -> after):",
    ]
    for key in ("completeness", "validity", "uniqueness", "schema_conformity"):
        b = before.get("components", {}).get(key)
        a = after.get("components", {}).get(key)
        if b is None and a is None:
            continue
        lines.append(f"  {key:18} {_fmt(b)} -> {_fmt(a)}")
    lines.append("")
    lines.append(
        "Completeness is compared on the columns that survived deduplication, so that "
        "removing a redundant full column is not read as a loss."
    )
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
