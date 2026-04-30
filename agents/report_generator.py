from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from state import PipelineState
from utils.prompts import load_prompt


class _ReportResponse(BaseModel):
    executive_summary: str
    dataset_overview: str
    quality_findings: str
    actions_taken: str
    recommendations: str


def report_generator_node(state: PipelineState) -> PipelineState:
    payload = _build_payload(state)
    system = load_prompt("report_generator")
    chain = ChatOpenAI(model="gpt-4o-mini", temperature=0).with_structured_output(_ReportResponse)

    result: _ReportResponse = chain.invoke([
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ])

    pdf = _render_pdf(state, result)
    out = _output_path(state)
    pdf.output(str(out))
    return state


# ── payload ───────────────────────────────────────────────────────────────────

def _build_payload(state: PipelineState) -> dict:
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
                "meaning": p.domain,
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
            }
            for r in state.duplicate_resolutions
        ],
        "classifications": [
            {
                "column_name": c.column_name,
                "normalized_name": c.normalized_name,
                "description": c.description,
            }
            for c in state.classifications
        ],
        "format_violations": [
            {"column_name": r.column_name, "violation_count": len(r.violations)}
            for r in state.validation_reports
            if r.violations
        ],
        "surviving_columns": state.surviving_columns,
        "errors": state.errors,
    }


# ── pdf renderer ──────────────────────────────────────────────────────────────

def _output_path(state: PipelineState) -> Path:
    if state.dataset_path:
        return Path(state.dataset_path).with_suffix(".pdf")
    return Path("report.pdf")


def _section(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.ln(3)


def _body(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 6, text)
    pdf.ln(4)


def _render_pdf(state: PipelineState, report: _ReportResponse) -> FPDF:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Data Quality Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Dataset   : {state.dataset_path or 'N/A'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 5, f"Domain    : {state.detected_domain or 'N/A'}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

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
