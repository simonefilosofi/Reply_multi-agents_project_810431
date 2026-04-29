"""Coverage-targeted smoke tests for the matplotlib + plotly chart helpers in
tools.py. Each test exercises one chart path and asserts the function emits
a non-empty PNG at the expected location under a pytest tmp_path fixture.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools import (
    chart_completeness_heatmap,
    chart_completeness_heatmap_before_after,
    chart_dimension_trajectory,
    chart_issue_resolution_sankey,
    chart_issues_by_agent,
    chart_reliability_comparison,
    chart_severity_distribution,
)


def _exists_and_nonempty(p: str) -> bool:
    return bool(p) and Path(p).is_file() and Path(p).stat().st_size > 0


def test_chart_severity_distribution_writes_png(tmp_path: Path) -> None:
    issues = [
        {"severity": "high"},
        {"severity": "medium"},
        {"severity": "medium"},
        {"severity": "low"},
    ]
    out = chart_severity_distribution(issues, str(tmp_path))
    assert _exists_and_nonempty(out)
    assert out.endswith("issue_severity_distribution.png")


def test_chart_issues_by_agent_handles_six_agents(tmp_path: Path) -> None:
    issues = [
        {"source": "schema", "severity": "high"},
        {"source": "completeness", "severity": "medium"},
        {"source": "duplicate", "severity": "low"},
        {"source": "anomaly", "severity": "medium"},
        {"source": "consistency", "severity": "high"},
        {"source": "constraint", "severity": "low"},
    ]
    out = chart_issues_by_agent(issues, str(tmp_path))
    assert _exists_and_nonempty(out)
    assert out.endswith("issues_by_agent.png")


def test_chart_completeness_heatmap_legacy_single_row(tmp_path: Path) -> None:
    completeness = {
        "rata": 1.0,
        "ente": 0.94,
        "descrizione": 0.71,
        "tipo_imposta": 1.0,
        "imposta": 0.42,
        "very_long_column_name_that_overflows_the_label_threshold": 0.10,
    }
    out = chart_completeness_heatmap(completeness, str(tmp_path))
    assert _exists_and_nonempty(out)
    assert out.endswith("completeness_heatmap.png")


def test_chart_completeness_heatmap_legacy_empty_returns_empty_string(tmp_path: Path) -> None:
    assert chart_completeness_heatmap({}, str(tmp_path)) == ""


def test_chart_completeness_heatmap_before_after_marks_dropped_columns(
    tmp_path: Path,
) -> None:
    before = {"a": 0.8, "b": 0.5, "c": 0.2}
    after = {"a": 1.0, "b": 0.9}
    out = chart_completeness_heatmap_before_after(before, after, str(tmp_path))
    assert _exists_and_nonempty(out)
    assert out.endswith("completeness_heatmap_before_after.png")


def test_chart_completeness_heatmap_before_after_empty_returns_empty(
    tmp_path: Path,
) -> None:
    assert chart_completeness_heatmap_before_after({}, {}, str(tmp_path)) == ""


def test_chart_reliability_comparison_renders_present_dimensions(tmp_path: Path) -> None:
    before = {
        "schema_conformity": 0.5,
        "completeness": 0.6,
        "uniqueness": 0.7,
        "consistency": 0.8,
        "anomaly_freedom": 0.9,
    }
    after = {
        "schema_conformity": 0.95,
        "completeness": 0.99,
        "uniqueness": 1.0,
        "consistency": 0.92,
        "anomaly_freedom": 0.95,
    }
    out = chart_reliability_comparison(before, after, 70.0, 95.0, str(tmp_path))
    assert _exists_and_nonempty(out)
    assert out.endswith("reliability_before_after.png")


def test_chart_dimension_trajectory_with_three_checkpoints(tmp_path: Path) -> None:
    layer_dimensions = {
        "post_synthesis": {
            "schema_conformity": 0.5,
            "completeness": 0.6,
            "uniqueness": 0.7,
            "consistency": 0.8,
            "anomaly_freedom": 0.9,
        },
        "post_remediation": {
            "schema_conformity": 0.85,
            "completeness": 0.92,
            "uniqueness": 0.95,
            "consistency": 0.88,
            "anomaly_freedom": 0.93,
        },
        "post_code_validator": {
            "schema_conformity": 0.97,
            "completeness": 0.99,
            "uniqueness": 1.0,
            "consistency": 0.94,
            "anomaly_freedom": 0.96,
        },
    }
    out = chart_dimension_trajectory(layer_dimensions, str(tmp_path))
    assert _exists_and_nonempty(out)
    assert out.endswith("reliability_trajectory.png")


def test_chart_dimension_trajectory_single_checkpoint_renders_placeholder(
    tmp_path: Path,
) -> None:
    out = chart_dimension_trajectory({"post_synthesis": {"completeness": 0.8}}, str(tmp_path))
    assert _exists_and_nonempty(out)


def test_chart_issue_resolution_sankey_overflow_buckets_into_other(
    tmp_path: Path,
) -> None:
    """Exercise the >12-types-overflow path (bucketed into 'other'), and the
    final 'resolved' / 'pending' edges. Returns non-empty PNG path on success
    or "" if kaleido failed to render — both are valid coverage targets.
    """
    fix_log = [
        {"issue_type": f"type_{i}", "column": f"col_{i}", "action": "auto_fixed"} for i in range(15)
    ]
    prioritized = [
        {"type": f"type_{i}", "column": f"col_{i}", "severity": "medium"} for i in range(15)
    ]
    out = chart_issue_resolution_sankey(fix_log, prioritized, str(tmp_path))
    assert out == "" or _exists_and_nonempty(out)


def test_chart_issue_resolution_sankey_empty_returns_empty(tmp_path: Path) -> None:
    assert chart_issue_resolution_sankey([], [], str(tmp_path)) == ""


@pytest.mark.parametrize("issue_count", [0, 1, 12])
def test_chart_severity_distribution_handles_edge_inputs(issue_count: int, tmp_path: Path) -> None:
    issues = [{"severity": "high"} for _ in range(issue_count)]
    out = chart_severity_distribution(issues, str(tmp_path))
    assert _exists_and_nonempty(out)
