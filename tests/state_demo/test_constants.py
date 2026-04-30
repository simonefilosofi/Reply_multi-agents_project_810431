"""Tests for state_demo.constants: subset coverage and date-pattern ordering."""

from __future__ import annotations

from state.constants import (
    ANOMALY_ISSUE_TYPES,
    COMPLETENESS_ISSUE_TYPES,
    CONSISTENCY_ISSUE_TYPES,
    CONSTRAINT_ISSUE_TYPES,
    DATE_FORMAT_MAP,
    DATE_PATTERNS,
    DUPLICATE_ISSUE_TYPES,
    GAP_DETECTION_ISSUE_TYPES,
    ISSUE_TYPES,
    SCHEMA_ISSUE_TYPES,
)


def test_per_agent_subset_coverage() -> None:
    """Every per-agent subset must be a subset of the master ISSUE_TYPES vocabulary."""
    union = (
        SCHEMA_ISSUE_TYPES
        | COMPLETENESS_ISSUE_TYPES
        | DUPLICATE_ISSUE_TYPES
        | ANOMALY_ISSUE_TYPES
        | CONSISTENCY_ISSUE_TYPES
        | CONSTRAINT_ISSUE_TYPES
    )
    missing = union - set(ISSUE_TYPES)
    assert not missing, f"Per-agent subsets reference unknown issue keys: {sorted(missing)}"


def test_gap_detection_subset_coverage() -> None:
    """GAP_DETECTION_ISSUE_TYPES must be a subset of the master vocabulary."""
    missing = GAP_DETECTION_ISSUE_TYPES - set(ISSUE_TYPES)
    assert not missing, f"GAP_DETECTION_ISSUE_TYPES references unknown keys: {sorted(missing)}"


def test_per_agent_partition_is_disjoint_except_known_overlaps() -> None:
    """Per-agent subsets should not overlap (each issue type owned by one agent)."""
    subsets = {
        "schema": SCHEMA_ISSUE_TYPES,
        "completeness": COMPLETENESS_ISSUE_TYPES,
        "duplicate": DUPLICATE_ISSUE_TYPES,
        "anomaly": ANOMALY_ISSUE_TYPES,
        "consistency": CONSISTENCY_ISSUE_TYPES,
        "constraint": CONSTRAINT_ISSUE_TYPES,
    }
    seen: dict[str, str] = {}
    overlaps: list[tuple[str, str, str]] = []
    for agent, types in subsets.items():
        for t in types:
            if t in seen:
                overlaps.append((t, seen[t], agent))
            else:
                seen[t] = agent
    assert not overlaps, f"Issue types claimed by multiple agents: {overlaps}"


def test_date_patterns_iso_with_time_first() -> None:
    """ISO 8601 with time component must be tried before ambiguous DD/MM patterns."""
    labels = [name for name, _ in DATE_PATTERNS]
    iso_t_idx = labels.index("YYYY-MM-DDTHH:MM:SS")
    ddmm_idx = labels.index("DD/MM/YYYY")
    assert iso_t_idx < ddmm_idx, (
        f"ISO timestamp pattern must precede DD/MM/YYYY in DATE_PATTERNS; "
        f"got iso_t at {iso_t_idx}, dd/mm at {ddmm_idx}"
    )


def test_date_format_map_covers_every_pattern() -> None:
    """Every DATE_PATTERNS label must have a corresponding strftime in DATE_FORMAT_MAP."""
    pattern_labels = {name for name, _ in DATE_PATTERNS}
    map_labels = set(DATE_FORMAT_MAP)
    assert pattern_labels == map_labels, (
        f"DATE_PATTERNS / DATE_FORMAT_MAP label mismatch: "
        f"only-in-patterns={sorted(pattern_labels - map_labels)} "
        f"only-in-map={sorted(map_labels - pattern_labels)}"
    )
