"""The six figures the notebook and the README both show. Each builder reads a recorded run's own
report JSON and per-stage timings and computes nothing of its own, so a figure cannot disagree with
the table printed beside it, and both documents draw the same figure from the same code rather than
two that can drift apart. Every chart paints an opaque page: the notebook renders these inline, and
on a dark editor theme a transparent figure leaves dark ink on a dark ground.

    python figures.py        regenerates images/ from runs/
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
IMAGES = ROOT / "images"

INK, ACCENT, SOFT, MUTED, PAPER = "#0b3d0b", "#02b900", "#9ae399", "#4a7a4a", "#ffffff"
ALERT = "#c00000"
DPI = 170
LLM_STAGES = frozenset({
    "profiler", "semantic", "duplicate_column", "format_consistency",
    "anomaly_detector", "unified", "report_generator",
})

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
    "figure.facecolor": PAPER, "axes.facecolor": PAPER,
    "savefig.facecolor": PAPER, "savefig.edgecolor": PAPER, "savefig.transparent": False,
})


def load_run(run_dir: Path | str) -> tuple[dict, dict]:
    """The report payload and the per-stage timings of one recorded run."""
    directory = Path(run_dir)
    report = directory / f"{directory.name}.json"
    if not report.exists():
        raise FileNotFoundError(
            f"{report} is missing. Record the run first:\n"
            f"    python record_run.py <source csv> {directory}"
        )
    timings = json.loads((directory / "timings.json").read_text(encoding="utf-8"))
    return json.loads(report.read_text(encoding="utf-8")), timings


def reliability_dimensions(report: dict) -> Figure:
    """Each quality dimension before and after remediation, scored like-for-like."""
    like_for_like = report["quality"]["like_for_like"]
    dimensions = like_for_like["dimensions"]
    before = [like_for_like["before"]["components"][d] for d in dimensions]
    after = [like_for_like["after"]["components"][d] for d in dimensions]

    fig, ax = plt.subplots(figsize=(7.8, 3.6))
    y = np.arange(len(dimensions))
    height = 0.38
    ax.barh(y + height / 2, before, height, color=SOFT,
            label=f"before  (score {like_for_like['before']['score']:.3f})")
    ax.barh(y - height / 2, after, height, color=ACCENT,
            label=f"after  (score {like_for_like['after']['score']:.3f})")
    for index, (b, a) in enumerate(zip(before, after)):
        ax.text(b + 0.002, index + height / 2, f"{b:.4f}", va="center", fontsize=9, color=MUTED)
        ax.text(a + 0.002, index - height / 2, f"{a:.4f}", va="center", fontsize=9, color=INK,
                fontweight="bold")
    ax.set_yticks(y, [d.replace("_", " ") for d in dimensions])
    ax.set_xlim(min(before + after) - 0.06, 1.025)
    ax.set_xlabel("score")
    ax.set_title(f"Reliability by dimension, like-for-like ({_name(report)})",
                 fontweight="bold", fontsize=13)
    _bare(ax, keep=("left",))
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
    return fig


def completeness_journey(report: dict) -> Figure:
    """Completeness at the raw file, once disguised nulls are unmasked, and as delivered."""
    snapshots = report["quality"]["snapshots"]
    hidden = report["quality"]["hidden_defects_unmasked"]
    values = [snapshots[name]["completeness"] for name in ("raw", "detected", "final")]
    labels = ["raw file\nas received", "after unmasking\ndisguised nulls", "as delivered"]

    fig, ax = plt.subplots(figsize=(6.9, 3.6))
    ax.bar(range(3), values, 0.55, color=[SOFT, "#5fce5f", ACCENT])
    for index, value in enumerate(values):
        ax.text(index, value + 0.002, f"{value:.4f}", ha="center", fontsize=11,
                fontweight="bold", color=INK)
    ax.annotate("", xy=(1, values[1]), xytext=(0, values[0] - 0.003),
                arrowprops=dict(arrowstyle="->", color=ALERT, lw=1.6))
    ax.text(0.5, values[1] - 0.008,
            f"-{hidden['disguised_nulls_unmasked']} disguised nulls found\n"
            "(completeness measured, not lost)",
            ha="center", va="top", fontsize=9, color=ALERT)
    ax.set_xticks(range(3), labels)
    ax.set_ylim(min(values) - 0.08, 1.0)
    ax.set_ylabel("completeness")
    ax.set_title(f"Completeness at the three measurement points ({_name(report)})",
                 fontweight="bold", fontsize=13)
    _bare(ax)
    ax.tick_params(axis="x", length=0)
    return fig


def violations_by_area(report: dict) -> Figure:
    """What detection found in each coverage area, against what still stands afterwards."""
    detected = report["violations_by_kind_detected"]
    residual = report["violations_by_kind_residual"]
    areas = [k for k in detected if detected[k] or residual.get(k)]
    found = [detected[k] for k in areas]
    left = [residual.get(k, 0) for k in areas]

    fig, ax = plt.subplots(figsize=(7.3, 3.6))
    x = np.arange(len(areas))
    width = 0.38
    ax.bar(x - width / 2, found, width, color=SOFT, label="detected")
    ax.bar(x + width / 2, [v if v else np.nan for v in left], width, color=ACCENT, label="residual")
    ax.set_yscale("symlog")
    for index, (d, r) in enumerate(zip(found, left)):
        ax.text(index - width / 2, d * 1.25, f"{d:,}", ha="center", fontsize=9, color=MUTED)
        ax.text(index + width / 2, (r * 1.25 if r else 1.3), f"{r:,}", ha="center", fontsize=9,
                color=INK, fontweight="bold")
    ax.set_xticks(x, areas)
    ax.set_ylabel("violations (log scale)")
    ax.set_title(f"Violations by coverage area, detected against residual ({_name(report)})",
                 fontweight="bold", fontsize=13)
    _bare(ax)
    ax.tick_params(axis="x", length=0)
    ax.legend(frameon=False, loc="upper right")
    return fig


def cells_changed_by_source(report: dict) -> Figure:
    """Every changed cell, attributed to the stage that changed it."""
    by_source = report["changes_summary"]["by_source"]
    total = report["changes_summary"]["total_cells_changed"]
    ranked = sorted(by_source.items(), key=lambda item: item[1], reverse=True)
    names = [name for name, _ in ranked]
    counts = [count for _, count in ranked]

    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    y = np.arange(len(names))[::-1]
    ax.barh(y, counts, 0.6, color=ACCENT)
    for position, count in zip(y, counts):
        ax.text(count + total * 0.008, position, f"{count:,}", va="center", fontsize=10, color=INK)
    ax.set_yticks(y, names)
    ax.set_xlabel("cells changed")
    ax.set_xlim(0, max(counts) * 1.12)
    ax.set_title(f"Where the {total:,} changed cells came from ({_name(report)})",
                 fontweight="bold", fontsize=13)
    _bare(ax, keep=("left",))
    ax.tick_params(axis="y", length=0)
    return fig


def stage_timings(timings: dict[str, float]) -> Figure:
    """Seconds per stage, with the stages that call a model drawn dark."""
    ranked = sorted(timings.items(), key=lambda item: item[1], reverse=True)
    names = [name for name, _ in ranked]
    seconds = [value for _, value in ranked]

    fig, ax = plt.subplots(figsize=(7.4, 4.1))
    y = np.arange(len(names))[::-1]
    ax.barh(y, seconds, 0.6, color=[ACCENT if n in LLM_STAGES else SOFT for n in names])
    for position, value in zip(y, seconds):
        ax.text(value + max(seconds) * 0.012, position, f"{value:.1f}s", va="center",
                fontsize=10, color=INK)
    ax.set_yticks(y, names)
    ax.set_xlabel("seconds")
    ax.set_xlim(0, max(seconds) * 1.06)
    ax.set_title(f"Where the {sum(seconds):.0f}s run spends its time (dark = calls a model)",
                 fontweight="bold", fontsize=13)
    _bare(ax, keep=("left",))
    ax.tick_params(axis="y", length=0)
    return fig


def reliability_across_datasets(reports: dict[str, dict]) -> Figure:
    """The like-for-like score at both ends of the run, for every dataset recorded."""
    labels = list(reports)
    before = [reports[label]["quality"]["like_for_like"]["before"]["score"] for label in labels]
    after = [reports[label]["quality"]["like_for_like"]["after"]["score"] for label in labels]

    fig, ax = plt.subplots(figsize=(7.8, 3.5))
    x = np.arange(len(labels))
    width = 0.38
    ax.bar(x - width / 2, before, width, color=SOFT, label="before remediation")
    ax.bar(x + width / 2, after, width, color=ACCENT, label="as delivered")
    for index, (b, a) in enumerate(zip(before, after)):
        ax.text(index - width / 2, b + 0.004, f"{b:.4f}", ha="center", fontsize=10, color=MUTED)
        ax.text(index + width / 2, a + 0.004, f"{a:.4f}", ha="center", fontsize=10, color=INK,
                fontweight="bold")
    ax.set_xticks(x, labels)
    ax.set_ylim(min(before) - 0.06, max(after) + 0.03)
    ax.set_ylabel("reliability, like-for-like")
    ax.set_title("Reliability across the recorded datasets", fontweight="bold", fontsize=13)
    _bare(ax)
    ax.tick_params(axis="x", length=0)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
    return fig


def to_png(fig: Figure) -> bytes:
    """The figure as PNG bytes on its own opaque page, for a notebook to display inline."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight", pad_inches=0.25,
                facecolor=PAPER, edgecolor=PAPER)
    plt.close(fig)
    return buffer.getvalue()


def save(fig: Figure, name: str) -> Path:
    IMAGES.mkdir(exist_ok=True)
    target = IMAGES / name
    target.write_bytes(to_png(fig))
    return target


def _name(report: dict) -> str:
    return Path(report.get("dataset_path", "dataset")).name


def _bare(ax, keep: tuple[str, ...] = ("left", "bottom")) -> None:
    for side in ("top", "right", "left", "bottom"):
        if side not in keep:
            ax.spines[side].set_visible(False)


if __name__ == "__main__":
    spesa, spesa_timings = load_run(RUNS / "spesa")
    across = {
        "spesa\n(required)": spesa,
        "attivazioniCessazioni\n(required)": load_run(RUNS / "attivazioniCessazioni")[0],
        "ritenuteSindacali\n(not developed against)": load_run(RUNS / "ritenuteSindacali")[0],
    }
    for figure, filename in (
        (reliability_dimensions(spesa), "reliability_dimensions.png"),
        (completeness_journey(spesa), "completeness_journey.png"),
        (violations_by_area(spesa), "violations_by_area.png"),
        (cells_changed_by_source(spesa), "cells_changed_by_source.png"),
        (stage_timings(spesa_timings), "stage_timings.png"),
        (reliability_across_datasets(across), "reliability_across_datasets.png"),
    ):
        print("wrote", save(figure, filename))
