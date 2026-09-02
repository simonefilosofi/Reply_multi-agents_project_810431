"""Pins the report's rendering layer: the inline SVG charts and the Markdown-to-HTML step that precedes the print. The PDF itself needs a browser, so these checks stop at the HTML, which is where every layout decision actually lives; the browser step is exercised by running the pipeline."""
from __future__ import annotations

from tools.md_to_pdf import markdown_to_html
from tools.report_charts import _LOW, _PAPER, dimension_comparison_chart, fill_rate_chart

_BEFORE = {"completeness": 0.8752, "uniqueness": 0.9881, "schema_conformity": 0.5}
_AFTER = {"completeness": 0.9801, "uniqueness": 1.0, "schema_conformity": 1.0}


def test_the_comparison_chart_draws_one_pair_per_shared_dimension() -> None:
    svg = dimension_comparison_chart(_BEFORE, _AFTER)

    assert svg.count("<rect") == len(_BEFORE) * 2 + 3
    assert "as delivered" in svg and "after remediation" in svg


def test_a_dimension_measured_only_after_remediation_is_left_out() -> None:
    svg = dimension_comparison_chart({"completeness": 0.9}, {"completeness": 1.0, "validity": 1.0})

    assert "validity" not in svg
    assert "completeness" in svg


def test_charts_return_empty_when_there_is_nothing_to_draw() -> None:
    assert dimension_comparison_chart({}, {}) == ""
    assert dimension_comparison_chart({"a": 1.0}, {"b": 1.0}) == ""
    assert fill_rate_chart({}) == ""


def test_the_fill_chart_ranks_the_emptiest_columns_first() -> None:
    svg = fill_rate_chart({"full": 1.0, "empty": 0.02, "half": 0.5}, limit=2)

    assert svg.index("empty") < svg.index("half")
    assert "full" not in svg


def test_a_column_below_the_threshold_is_drawn_in_a_different_tone() -> None:
    assert _LOW in fill_rate_chart({"sparse": 0.2})
    assert _LOW not in fill_rate_chart({"complete": 0.99})


def test_a_rate_outside_the_unit_interval_cannot_overflow_the_plot() -> None:
    svg = fill_rate_chart({"broken": 4.0})

    assert "width='470.0'" in svg


def test_a_column_name_carrying_markup_is_escaped() -> None:
    svg = fill_rate_chart({"a<b>&c": 0.5})

    assert "<b>" not in svg
    assert "&lt;b&gt;" in svg


def test_markdown_tables_survive_the_conversion() -> None:
    html = markdown_to_html("| a | b |\n|---|---|\n| 1 | 2 |", "T")

    assert "<table>" in html and "<th>a</th>" in html and "<td>1</td>" in html


def test_a_fenced_code_block_survives_the_conversion() -> None:
    html = markdown_to_html("```python\ndef clean_value(value):\n    return value\n```", "T")

    assert "<pre>" in html and "clean_value" in html


def test_inline_svg_reaches_the_html_unescaped() -> None:
    html = markdown_to_html(f"# T\n\n{dimension_comparison_chart(_BEFORE, _AFTER)}", "T")

    assert "<svg" in html and "&lt;svg" not in html


def test_the_running_header_and_footer_are_repeatable_table_sections() -> None:
    html = markdown_to_html("# T", "Report title", "footer note")

    assert "<thead>" in html and "<tfoot>" in html
    assert "display: table-header-group" in html
    assert "Report title" in html and "footer note" in html


def test_a_chart_carries_its_own_background_so_it_reads_on_any_page() -> None:
    """The charts are written into the Markdown as bare SVG and rendered wherever the report is
    read - the notebook among them. Drawn on a transparent canvas the dark ink vanished against a
    dark page, so each chart paints its own paper before anything else."""
    for svg in (dimension_comparison_chart(_BEFORE, _AFTER), fill_rate_chart({"sparse": 0.2})):
        assert f"fill='{_PAPER}'" in svg
        assert svg.index(_PAPER) < svg.index("<text")
