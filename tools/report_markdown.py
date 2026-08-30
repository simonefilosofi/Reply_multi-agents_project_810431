"""Builds the data quality report as Markdown from the run payload. Every figure in the document is computed here from the pipeline's own measurements; the model contributes only the verdict, one comment per coverage area, and the recommendations, so a wrong number cannot enter the report through a sentence. The document follows the reader rather than the pipeline: what arrived, what was wrong with it, what was changed, what was delivered, and what is still open. It is a pure function of the payload and the commentary, so it can be built and checked without a model, a browser, or a dataset."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from tools.report_charts import dimension_comparison_chart, fill_rate_chart

_AREAS = (
    ("schema", "Schema validation", "schema_comment"),
    ("completeness", "Completeness", "completeness_comment"),
    ("consistency", "Consistency", "consistency_comment"),
    ("anomaly", "Anomaly detection", "anomaly_comment"),
    ("remediation", "Remediation", "remediation_comment"),
)
_MAX_LISTED_COLUMNS = 12
_MAX_LISTED_PROPOSALS = 20
_MAX_PLACEHOLDER_COLUMNS = 10


def build_report_markdown(payload: dict, commentary: dict) -> str:
    """The whole document. Sections that have nothing to say drop out rather than printing a
    heading over an empty table."""
    sections = [
        _header(payload),
        _verdict(payload, commentary),
        _received(payload),
        _findings(payload, commentary),
        _changes(payload),
        _delivered(payload),
        _recommendations(commentary),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def _header(payload: dict) -> str:
    name = Path(payload.get("dataset_path") or "dataset").name
    meta = [
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"domain {payload.get('detected_domain') or 'not detected'}",
        f"language {payload.get('detected_language') or 'not detected'}",
    ]
    return f"# Data Quality Report - {name}\n\n<sub>{' | '.join(meta)}</sub>"


def _verdict(payload: dict, commentary: dict) -> str:
    quality = payload.get("quality") or {}
    delivered = quality.get("as_delivered") or {}
    before, after = delivered.get("before") or {}, delivered.get("after") or {}
    if before.get("score") is None or after.get("score") is None:
        return _paragraph("## Verdict", commentary.get("verdict"))

    lines = [
        "## Verdict",
        "",
        f"**Reliability {before['score']:.3f} to {after['score']:.3f}** over "
        f"{', '.join(delivered.get('dimensions') or []) or 'no measurable dimension'}. "
        "The score is a geometric mean, so one broken dimension pulls it down rather than "
        "being averaged away.",
    ]
    excluded = quality.get("dimensions_excluded") or []
    if excluded:
        lines.append(
            f"Not measurable on the file as delivered, and therefore outside this figure: "
            f"{', '.join(excluded)}."
        )
    chart = dimension_comparison_chart(
        before.get("components") or {},
        after.get("components") or {},
        "Quality dimensions, as delivered against remediated",
    )
    if chart:
        lines += ["", chart]
    if commentary.get("verdict"):
        lines += ["", commentary["verdict"]]
    return "\n".join(lines)


def _received(payload: dict) -> str:
    shape = payload.get("shape") or {}
    quality = payload.get("quality") or {}
    before = quality.get("headline_before") or {}
    rows, columns = shape.get("rows"), shape.get("columns")
    counts = [
        ["rows", _number(before.get("rows", rows))],
        ["columns", _number(before.get("columns", columns))],
        ["null cells", _number(before.get("null_cells"))],
        ["nulls disguised as values", _number(
            (quality.get("hidden_defects_unmasked") or {}).get("disguised_nulls_unmasked")
        )],
        ["duplicate rows", _number(before.get("duplicate_rows"))],
        ["rows in key conflict", _number(before.get("rows_in_key_conflict"))],
        ["columns badly named", _number(before.get("columns_badly_named"))],
        ["columns almost empty", _number(before.get("columns_sparse"))],
        ["columns duplicating another", _number(before.get("columns_redundant"))],
    ]
    lines = [
        "## The dataset as received",
        "",
        _table(["measure", "value"], [row for row in counts if row[1] != "n/a"]),
    ]
    hidden = quality.get("hidden_defects_unmasked") or {}
    if hidden.get("disguised_nulls_unmasked"):
        lines += ["", (
            f"Completeness read {_percent(hidden.get('apparent_completeness'))} on the file as "
            f"delivered and {_percent(hidden.get('true_completeness'))} once the placeholders "
            f"standing in for gaps were counted as gaps. The lower figure is the accurate one."
        )]
    faults = _fault_table(payload)
    if faults:
        lines += ["", "### What was wrong, by coverage area", "", faults]
    return "\n".join(lines)


def _fault_table(payload: dict) -> str:
    detected = payload.get("violations_by_kind_detected") or {}
    naming = payload.get("naming_violations") or []
    anomalies = payload.get("anomalies") or []
    duplicates = payload.get("duplicate_resolutions") or []
    rows = [
        [
            "Schema validation",
            f"{len(naming)} names against convention, "
            f"{_number(detected.get('schema'))} schema violations",
            ", ".join(f"`{item['column_name']}`" for item in naming[:3]) or "-",
        ],
        [
            "Completeness",
            f"{_number(detected.get('completeness'))} completeness violations",
            _placeholder_example(payload),
        ],
        [
            "Consistency",
            f"{_number(detected.get('consistency'))} cross-column violations, "
            f"{len(duplicates)} duplicate column groups",
            ", ".join(f"`{group['canonical_name']}`" for group in duplicates[:3]) or "-",
        ],
        [
            "Anomaly detection",
            f"{sum(int(a.get('detected') or 0) for a in anomalies)} across "
            f"{len(anomalies)} columns",
            ", ".join(f"`{a['column_name']}`" for a in anomalies[:3]) or "-",
        ],
        [
            "Format validity",
            f"{_number(detected.get('format'))} format violations",
            ", ".join(
                f"`{item['column_name']}`"
                for item in (payload.get("format_violations_detected") or [])[:3]
            ) or "-",
        ],
    ]
    return _table(["area", "detected", "for example"], rows)


def _findings(payload: dict, commentary: dict) -> str:
    blocks = ["## What the pipeline found"]
    for _key, title, comment_field in _AREAS:
        body = _area_body(_key, payload)
        comment = commentary.get(comment_field)
        if not body and not comment:
            continue
        blocks.append(f"### {title}")
        if body:
            blocks.append(body)
        if comment:
            blocks.append(comment)
    return "\n\n".join(blocks) if len(blocks) > 1 else ""


def _area_body(area: str, payload: dict) -> str:
    if area == "schema":
        return _schema_body(payload)
    if area == "completeness":
        return _completeness_body(payload)
    if area == "consistency":
        return _consistency_body(payload)
    if area == "anomaly":
        return _anomaly_body(payload)
    return _remediation_body(payload)


def _schema_body(payload: dict) -> str:
    naming = payload.get("naming_violations") or []
    sparse = ((payload.get("completeness") or {}).get("sparse_columns")) or []
    blocks = []
    if naming:
        blocks.append(_table(
            ["column", "suggested name"],
            [[f"`{item['column_name']}`", f"`{item['suggested_name']}`"] for item in naming],
        ))
    if sparse:
        blocks.append(_table(
            ["column too empty to inform", "nulls", "null rate"],
            [
                [f"`{item['column']}`", _number(item["nulls"]), _percent(item["null_rate"])]
                for item in sparse
            ],
        ))
    return "\n\n".join(blocks)


def _completeness_body(payload: dict) -> str:
    completeness = payload.get("completeness") or {}
    overall = completeness.get("overall") or {}
    rows_view = completeness.get("rows") or {}
    by_column = completeness.get("by_column") or {}
    blocks = []
    if overall:
        blocks.append(_table(
            ["measure", "value"],
            [
                ["overall fill rate", _percent(overall.get("completeness"))],
                ["null cells", f"{_number(overall.get('null_cells'))} of {_number(overall.get('cells'))}"],
                ["rows with no gaps", _number(rows_view.get("complete_rows"))],
                ["rows carrying a gap", _number(rows_view.get("rows_with_nulls"))],
            ],
        ))
    if overall:
        blocks.append(
            "These figures are measured once the placeholders standing in for gaps have been "
            "counted as gaps, so the null count is higher here than in the summary of the file "
            "as received, which reports what the file appeared to hold."
        )
    chart = fill_rate_chart(
        {column: stats["completeness"] for column, stats in by_column.items()},
        "Fill rate by column, least complete first",
    )
    if chart:
        blocks.append(chart)
    placeholders = _placeholder_rows(payload)
    if placeholders:
        blocks.append(_table(["column", "values that stood in for a gap"], placeholders))
    return "\n\n".join(blocks)


def _consistency_body(payload: dict) -> str:
    duplicates = payload.get("duplicate_resolutions") or []
    duplicate_rows = payload.get("duplicate_rows") or {}
    blocks = []
    if duplicates:
        blocks.append(_table(
            ["group kept as", "data taken from", "columns removed",
             "cells backfilled", "cells overwritten", "values lost"],
            [
                [
                    f"`{group['canonical_name']}`",
                    f"`{group.get('survivor')}`",
                    ", ".join(f"`{name}`" for name in group.get("dropped") or []) or "-",
                    _number(group.get("cells_backfilled")),
                    _number(sum((group.get("cells_overwritten") or {}).values())),
                    _number(sum(len(values) for values in (group.get("values_lost") or {}).values())),
                ]
                for group in duplicates
            ],
        ))
    exact = duplicate_rows.get("exact_duplicates")
    if exact is not None:
        blocks.append(
            f"Exact duplicate rows removed: **{_number(exact)}**. "
            f"Records sharing a key while carrying different data are reported, never removed."
        )
    return "\n\n".join(blocks)


def _anomaly_body(payload: dict) -> str:
    anomalies = payload.get("anomalies") or []
    if not anomalies:
        return ""
    return "\n\n".join([
        _table(
            ["column", "method", "detected", "for example"],
            [
                [
                    f"`{item['column_name']}`",
                    item.get("method", "-"),
                    _number(item.get("detected")),
                    ", ".join(f"`{value}`" for value in (item.get("examples") or [])[:3]) or "-",
                ]
                for item in anomalies
            ],
        ),
        "An outlier is unusual, which is not the same as wrong: these are reported and, unless "
        "the value is impossible for the column's meaning, left for a person to judge.",
    ])


def _remediation_body(payload: dict) -> str:
    proposals = payload.get("proposed_remediations") or []
    auto = payload.get("auto_remediations") or []
    applied = [p for p in proposals if p.get("applied")]
    generated = [p for p in proposals if p.get("generated_sources")]
    return _table(
        ["measure", "value"],
        [
            ["corrections applied automatically", _number(len(auto))],
            ["proposals put to the reviewer", _number(len(proposals))],
            ["proposals accepted", _number(len(applied))],
            ["proposals carrying a generated function", _number(len(generated))],
            ["cells changed in total", _number((payload.get("changes_summary") or {}).get("total_cells_changed"))],
        ],
    )


def _changes(payload: dict) -> str:
    auto = payload.get("auto_remediations") or []
    proposals = payload.get("proposed_remediations") or []
    changes = payload.get("changes_summary") or {}
    if not auto and not proposals:
        return ""
    blocks = ["## What was changed"]

    if auto:
        blocks.append("### Applied without asking, because the data determined them")
        blocks.append(_table(
            ["column", "correction", "cells", "why it needed no approval"],
            [
                [
                    f"`{item.get('column')}`",
                    item.get("operation", "-"),
                    _number(item.get("cells_changed")),
                    item.get("rationale", "-"),
                ]
                for item in auto
            ],
        ))

    if proposals:
        blocks.append("### Put to the reviewer")
        blocks.append(_table(
            ["id", "columns", "what it does", "outcome"],
            [
                [
                    f"`{item['id']}`",
                    ", ".join(f"`{c}`" for c in item.get("affected_columns") or []) or "-",
                    item.get("description", "-"),
                    "accepted" if item.get("applied") else "not applied",
                ]
                for item in proposals[:_MAX_LISTED_PROPOSALS]
            ],
        ))

    sources = _generated_sources(proposals)
    if sources:
        blocks.append("### Cleaning functions written for this dataset")
        blocks.append(
            "Each function below was refused any import outside `re`, `datetime`, `decimal` and "
            "`math`, executed in a sandbox against the column's own conforming and violating "
            "values, and read by a person before it ran. This is the code that was executed."
        )
        blocks.extend(sources)

    by_column = changes.get("by_column") or {}
    if by_column:
        blocks.append("### Cells changed, by column")
        blocks.append(_table(
            ["column", "cells changed"],
            [
                [f"`{column}`", _number(count)]
                for column, count in list(by_column.items())[:_MAX_LISTED_COLUMNS]
            ],
        ))
    return "\n\n".join(blocks)


def _generated_sources(proposals: list[dict]) -> list[str]:
    blocks = []
    for proposal in proposals:
        for source in proposal.get("generated_sources") or []:
            columns = ", ".join(f"`{c}`" for c in proposal.get("affected_columns") or [])
            blocks.append(f"On {columns}:\n\n```python\n{source.strip()}\n```")
    return blocks


def _delivered(payload: dict) -> str:
    quality = payload.get("quality") or {}
    before = quality.get("headline_before") or {}
    after = quality.get("headline_after") or {}
    if not before or not after:
        return ""
    measures = [
        ("rows", "rows"), ("columns", "columns"), ("null cells", "null_cells"),
        ("format violations", "format_violations"), ("inconsistent rows", "inconsistent_rows"),
        ("duplicate rows", "duplicate_rows"), ("rows in key conflict", "rows_in_key_conflict"),
        ("columns badly named", "columns_badly_named"),
        ("columns almost empty", "columns_sparse"),
        ("columns duplicating another", "columns_redundant"),
    ]
    rows = [
        [label, _number(before.get(key)), _number(after.get(key))]
        for label, key in measures
        if before.get(key) is not None or after.get(key) is not None
    ]
    blocks = [
        "## The dataset as delivered",
        "",
        _table(["measure", "as received", "after remediation"], rows),
    ]
    like_for_like = quality.get("like_for_like") or {}
    scoped_before = (like_for_like.get("before") or {}).get("score")
    scoped_after = (like_for_like.get("after") or {}).get("score")
    if scoped_before is not None and scoped_after is not None:
        blocks.append(
            f"Restricted to the columns present at both ends, reliability moved from "
            f"**{scoped_before:.3f}** to **{scoped_after:.3f}**. The headline "
            f"pair counts the columns the pipeline removed; this one does not, so removing an "
            f"empty column is not read as an improvement."
        )
    residual = payload.get("violations_by_kind_residual") or {}
    open_items = [f"{count} {kind}" for kind, count in residual.items() if count]
    blocks.append(
        f"Still open: {', '.join(open_items)}." if open_items
        else "No violation remains in any category."
    )
    return "\n\n".join(blocks)


def _recommendations(commentary: dict) -> str:
    items = commentary.get("recommendations") or []
    if not items:
        return ""
    return "\n".join(["## Recommendations", ""] + [f"{i}. {text}" for i, text in enumerate(items, 1)])


def _placeholder_rows(payload: dict) -> list[list[str]]:
    rows = []
    for column in payload.get("semantic_payload") or []:
        placeholders = column.get("placeholders_found") or []
        if placeholders:
            rows.append([
                f"`{column['column_name']}`",
                ", ".join(f"`{value}`" for value in placeholders[:8]),
            ])
    return rows[:_MAX_PLACEHOLDER_COLUMNS]


def _placeholder_example(payload: dict) -> str:
    for column in payload.get("semantic_payload") or []:
        placeholders = column.get("placeholders_found") or []
        if placeholders:
            return ", ".join(f"`{value}`" for value in placeholders[:3])
    return "-"


def _paragraph(heading: str, text: str | None) -> str:
    return f"{heading}\n\n{text}" if text else ""


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return ""
    body = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    body += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join(body)


def _cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _number(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.3f}"
    return f"{int(value):,}"


def _percent(value) -> str:
    return "n/a" if value is None else f"{float(value):.1%}"
