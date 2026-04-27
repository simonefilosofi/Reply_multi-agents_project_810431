"""Tests for IngestionAgent's structural sanity-check fields added in Step 8.

Covers total_cells / empty_cell_rate / wholly_empty_rows / wholly_empty_cols
in PipelineState.ingestion_meta, including the all-empty edge case.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from agents_demo.ingestion_agent import IngestionAgent
from state_demo.pipeline_state import PipelineState


def _write_csv(path: Path, df: pd.DataFrame) -> str:
    df.to_csv(path, index=False)
    return str(path)


def test_ingestion_meta_records_structural_sanity_checks(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "name": ["Alice", "", "Carlo", "Dario"],
            "city": ["Roma", "Milano", "n.d.", "Bari"],
            "phantom": ["", "", "", ""],
        }
    )
    src = _write_csv(tmp_path / "with_holes.csv", df)
    state = PipelineState(source_path=src)

    IngestionAgent(state).run("ingest")

    meta = state.ingestion_meta
    assert meta["rows"] == 4
    assert meta["columns"] == 3
    assert meta["total_cells"] == 12
    assert meta["wholly_empty_cols"] == 1
    assert meta["wholly_empty_rows"] == 0
    assert meta["empty_cell_rate"] == 0.5


def test_ingestion_meta_handles_zero_row_dataframe(tmp_path: Path) -> None:
    src = tmp_path / "headers_only.csv"
    src.write_text("a,b,c\n", encoding="utf-8")
    state = PipelineState(source_path=str(src))

    IngestionAgent(state).run("ingest")

    meta = state.ingestion_meta
    assert meta["rows"] == 0
    assert meta["total_cells"] == 0
    assert meta["empty_cell_rate"] == 0.0
    assert meta["wholly_empty_rows"] == 0
    assert meta["wholly_empty_cols"] == 0


def test_ingestion_detects_wholly_empty_rows(tmp_path: Path) -> None:
    df = pd.DataFrame(
        {
            "x": ["a", "", "c", ""],
            "y": ["1", "n.d.", "3", ""],
        }
    )
    src = _write_csv(tmp_path / "with_blank_rows.csv", df)
    state = PipelineState(source_path=src)

    IngestionAgent(state).run("ingest")

    assert state.ingestion_meta["wholly_empty_rows"] == 2
    assert state.ingestion_meta["wholly_empty_cols"] == 0
