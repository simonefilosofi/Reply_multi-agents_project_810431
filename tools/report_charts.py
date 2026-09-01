"""Inline SVG charts for the data quality report. The report is print-first, so the charts are static SVG strings written straight into the Markdown: no plotting library, no image files, nothing for the PDF step to resolve. Two shapes cover what the report needs to show - a paired bar comparing each quality dimension before and after remediation, and a single bar ranking columns by fill rate - and both degrade to an empty string when there is nothing to draw, so a caller can concatenate the result unconditionally."""
from __future__ import annotations

_INK = "#0b3d0b"
_BEFORE = "#9ae399"
_AFTER = "#02b900"
_GRID = "#ccf1cc"
_MUTED = "#4a7a4a"
_LOW = "#67d566"

_ROW_HEIGHT = 26
_BAR_HEIGHT = 9
_LABEL_WIDTH = 132
_VALUE_WIDTH = 58
_TOP = 26
_BOTTOM = 14
_LOW_FILL_THRESHOLD = 0.9


def dimension_comparison_chart(
    before: dict[str, float], after: dict[str, float], title: str = "", width: int = 660
) -> str:
    """Pairs every quality dimension with its remediated value. Dimensions measured only after
    remediation are left out rather than drawn against a zero, which would read as a collapse
    where there was simply no measurement."""
    shared = [name for name in before if name in after]
    if not shared:
        return ""
    height = _TOP + len(shared) * _ROW_HEIGHT + _BOTTOM
    plot_width = width - _LABEL_WIDTH - _VALUE_WIDTH
    parts = [_open(width, height), _title(title, 14), _legend(width, 14)]
    parts.extend(_gridlines(_LABEL_WIDTH, plot_width, _TOP - 8, height - _BOTTOM + 2))

    for index, name in enumerate(shared):
        top = _TOP + index * _ROW_HEIGHT
        parts.append(_label(name.replace("_", " "), top + _BAR_HEIGHT))
        parts.append(_bar(_LABEL_WIDTH, top - 1, plot_width * _clamp(before[name]), _BEFORE))
        parts.append(
            _bar(_LABEL_WIDTH, top + _BAR_HEIGHT + 1, plot_width * _clamp(after[name]), _AFTER)
        )
        parts.append(_value(
            width - 4, top + _BAR_HEIGHT + 3,
            f"{before[name]:.3f} to {after[name]:.3f}", _INK,
        ))

    parts.append("</svg>")
    return "".join(parts)


def fill_rate_chart(
    fill_by_column: dict[str, float], title: str = "", width: int = 660, limit: int = 14
) -> str:
    """Ranks the least complete columns. Anything at or above the threshold is drawn in the plain
    ink so the eye lands on the columns that are actually short of data."""
    ranked = sorted(fill_by_column.items(), key=lambda item: item[1])[:limit]
    if not ranked:
        return ""
    height = _TOP + len(ranked) * 18 + _BOTTOM
    plot_width = width - _LABEL_WIDTH - _VALUE_WIDTH
    parts = [_open(width, height), _title(title, 14)]
    parts.extend(_gridlines(_LABEL_WIDTH, plot_width, _TOP - 8, height - _BOTTOM + 2))

    for index, (column, rate) in enumerate(ranked):
        top = _TOP + index * 18
        colour = _LOW if rate < _LOW_FILL_THRESHOLD else _AFTER
        parts.append(_label(column, top + 8))
        parts.append(_bar(_LABEL_WIDTH, top, plot_width * _clamp(rate), colour))
        parts.append(_value(width - 4, top + 8, f"{rate:.1%}", _INK))

    parts.append("</svg>")
    return "".join(parts)


def _open(width: int, height: int) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}' font-family='Helvetica,Arial,sans-serif'>"
    )


def _title(text: str, baseline: int) -> str:
    if not text:
        return ""
    return (
        f"<text x='0' y='{baseline}' font-size='10.5' font-weight='bold' "
        f"fill='{_INK}'>{_escape(text)}</text>"
    )


def _gridlines(left: int, plot_width: float, top: float, bottom: float) -> list[str]:
    lines = []
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = left + plot_width * fraction
        lines.append(
            f"<line x1='{x:.1f}' y1='{top:.1f}' x2='{x:.1f}' y2='{bottom:.1f}' "
            f"stroke='{_GRID}' stroke-width='1'/>"
        )
        lines.append(
            f"<text x='{x:.1f}' y='{bottom + 10:.1f}' text-anchor='middle' font-size='7.5' "
            f"fill='{_MUTED}'>{int(fraction * 100)}%</text>"
        )
    return lines


def _bar(left: int, top: float, length: float, colour: str) -> str:
    return (
        f"<rect x='{left}' y='{top:.1f}' width='{max(length, 1):.1f}' "
        f"height='{_BAR_HEIGHT}' fill='{colour}' rx='1.5'/>"
    )


def _label(text: str, baseline: float) -> str:
    return (
        f"<text x='{_LABEL_WIDTH - 6}' y='{baseline:.1f}' text-anchor='end' font-size='8.5' "
        f"fill='{_INK}'>{_escape(_truncate(text, 24))}</text>"
    )


def _value(right: float, baseline: float, text: str, colour: str) -> str:
    return (
        f"<text x='{right:.1f}' y='{baseline:.1f}' text-anchor='end' font-size='8' "
        f"fill='{colour}'>{_escape(text)}</text>"
    )


def _legend(right: int, baseline: float) -> str:
    """Sits on the title line, clear of the axis labels a bottom legend would collide with."""
    after_x = right - 96
    before_x = right - 190
    return (
        f"<rect x='{before_x}' y='{baseline - 7:.1f}' width='9' height='7' fill='{_BEFORE}'/>"
        f"<text x='{before_x + 13}' y='{baseline:.1f}' font-size='7.5' "
        f"fill='{_MUTED}'>as delivered</text>"
        f"<rect x='{after_x}' y='{baseline - 7:.1f}' width='9' height='7' fill='{_AFTER}'/>"
        f"<text x='{after_x + 13}' y='{baseline:.1f}' font-size='7.5' "
        f"fill='{_MUTED}'>after remediation</text>"
    )


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _escape(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
