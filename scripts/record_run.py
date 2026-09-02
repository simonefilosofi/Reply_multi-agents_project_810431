"""Records one full pipeline run into a directory the notebook and the README figures replay from.
Runs the twelve nodes in the order graph.py fixes, times each, approves every proposal at the gate,
and leaves the report, the cleaned dataset, the cell-level change log and timings.json beside the
copy of the source CSV it worked on. Approving everything is the upper bound on what the system
does rather than its default: the Streamlit application is where a reviewer decides case by case.

    python record_run.py Datasets-Reply-20260313/project_data_quality/spesa.csv runs/spesa
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)

from agents.anomaly_detector import anomaly_detector_node
from agents.apply_fixes import apply_fixes_node
from agents.auto_remediation import auto_remediation_node
from agents.baseline_builder import baseline_builder_node
from agents.duplicate_column import duplicate_column_node
from agents.duplicate_row import duplicate_row_node
from agents.format_consistency import format_consistency_node
from agents.nan_handler import nan_handler_node
from agents.profiler import profiler_node
from agents.report_generator import report_generator_node
from agents.semantic import semantic_node
from agents.unified import unified_node
from state import PipelineState

DETECTION_NODES = (
    ("baseline_builder", baseline_builder_node),
    ("profiler", profiler_node),
    ("semantic", semantic_node),
    ("nan_handler", nan_handler_node),
    ("duplicate_column", duplicate_column_node),
    ("format_consistency", format_consistency_node),
    ("auto_remediation", auto_remediation_node),
    ("anomaly_detector", anomaly_detector_node),
    ("unified", unified_node),
)
DELIVERY_NODES = (
    ("apply_fixes", apply_fixes_node),
    ("duplicate_row", duplicate_row_node),
    ("report_generator", report_generator_node),
)


def record(source: Path, out_dir: Path) -> dict[str, float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    working = out_dir / source.name
    shutil.copy2(source, working)

    state = PipelineState(dataset=pd.read_csv(working), dataset_path=str(working))
    timings: dict[str, float] = {}

    for label, node in DETECTION_NODES:
        state = _timed(label, node, state, timings)

    approved = [proposal.id for proposal in state.proposed_fixes]
    print(f"gate: approving {len(approved)} of {len(state.proposed_fixes)} proposals", flush=True)
    state = state.model_copy(update={"approved_fix_ids": approved})

    for label, node in DELIVERY_NODES:
        state = _timed(label, node, state, timings)

    (out_dir / "timings.json").write_text(
        json.dumps(timings, indent=2), encoding="utf-8"
    )
    print(f"recorded {source.stem} in {sum(timings.values()):.1f}s -> {out_dir}", flush=True)
    if state.errors:
        print("errors:", state.errors, flush=True)
    return timings


def _timed(
    label: str,
    node: Callable[[PipelineState], PipelineState],
    state: PipelineState,
    timings: dict[str, float],
) -> PipelineState:
    started = time.time()
    state = node(state)
    timings[label] = round(time.time() - started, 2)
    print(f"[{label:20}] {timings[label]:7.2f}s", flush=True)
    return state


if __name__ == "__main__":
    record(Path(sys.argv[1]), Path(sys.argv[2]))
