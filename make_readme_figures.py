"""Regenerates the figures the README's Section 4 references. It reads only a run's own
report JSON and per-stage timings from out/ and emits the PNGs the README references into images/.
It computes nothing of its own, so a figure cannot disagree with the report printed beside it.

    pip install matplotlib
    python make_readme_figures.py
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).parent
RUN = ROOT / "out" / "readme_run"
IMG = ROOT / "images"
IMG.mkdir(exist_ok=True)
D = json.loads((RUN / "spesa.json").read_text())
T = json.loads((RUN / "timings.json").read_text())

INK, ACCENT, SOFT, MUTED = "#0b3d0b", "#02b900", "#9ae399", "#4a7a4a"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.edgecolor": MUTED, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.titlecolor": INK,
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMG / name, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def _bare(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        if side not in keep:
            ax.spines[side].set_visible(False)


# 1. reliability by dimension, like-for-like
ll = D["quality"]["like_for_like"]
dims = ll["dimensions"]
before = [ll["before"]["components"][d] for d in dims]
after = [ll["after"]["components"][d] for d in dims]

fig, ax = plt.subplots(figsize=(7.8, 3.6))
y = np.arange(len(dims))
h = 0.38
ax.barh(y + h / 2, before, h, color=SOFT, label=f"before  (score {ll['before']['score']:.3f})")
ax.barh(y - h / 2, after, h, color=ACCENT, label=f"after  (score {ll['after']['score']:.3f})")
for i, (b, a) in enumerate(zip(before, after)):
    ax.text(b + 0.002, i + h / 2, f"{b:.4f}", va="center", fontsize=9, color=MUTED)
    ax.text(a + 0.002, i - h / 2, f"{a:.4f}", va="center", fontsize=9, color=INK, fontweight="bold")
ax.set_yticks(y, [d.replace("_", " ") for d in dims])
ax.set_xlim(0.80, 1.025)
ax.set_xlabel("score")
ax.set_title("Reliability by dimension, like-for-like (spesa.csv)", fontweight="bold", fontsize=13)
_bare(ax, keep=("left",))
ax.tick_params(axis="y", length=0)
ax.set_xticks([0.80, 0.85, 0.90, 0.95, 1.00])
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
save(fig, "reliability_dimensions.png")


# 2. completeness at the three measurement points
snaps = D["quality"]["snapshots"]
hidden = D["quality"]["hidden_defects_unmasked"]
vals = [snaps["raw"]["completeness"], snaps["detected"]["completeness"], snaps["final"]["completeness"]]
labels = ["raw file\nas received", "after unmasking\ndisguised nulls", "as delivered"]

fig, ax = plt.subplots(figsize=(6.9, 3.6))
ax.bar(range(3), vals, 0.55, color=[SOFT, "#5fce5f", ACCENT])
for i, v in enumerate(vals):
    ax.text(i, v + 0.002, f"{v:.4f}", ha="center", fontsize=11, fontweight="bold", color=INK)
ax.annotate(
    "", xy=(1, vals[1]), xytext=(0, vals[0] - 0.003),
    arrowprops=dict(arrowstyle="->", color="#c00000", lw=1.6),
)
ax.text(
    0.5, vals[1] - 0.008,
    f"-{hidden['disguised_nulls_unmasked']} disguised nulls found\n(completeness measured, not lost)",
    ha="center", va="top", fontsize=9, color="#c00000",
)
ax.set_xticks(range(3), labels)
ax.set_ylim(0.80, 1.0)
ax.set_ylabel("completeness")
ax.set_title("Completeness at the three measurement points (spesa.csv)", fontweight="bold", fontsize=13)
_bare(ax)
ax.tick_params(axis="x", length=0)
save(fig, "completeness_journey.png")


# 3. violations by coverage area, detected vs residual
det, res = D["violations_by_kind_detected"], D["violations_by_kind_residual"]
areas = [k for k in det if det[k] or res.get(k)]
dv = [det[k] for k in areas]
rv = [res.get(k, 0) for k in areas]

fig, ax = plt.subplots(figsize=(7.3, 3.6))
x = np.arange(len(areas))
w = 0.38
ax.bar(x - w / 2, dv, w, color=SOFT, label="detected")
ax.bar(x + w / 2, [v if v else np.nan for v in rv], w, color=ACCENT, label="residual")
ax.set_yscale("symlog")
for i, (d, r) in enumerate(zip(dv, rv)):
    ax.text(i - w / 2, d * 1.25, f"{d:,}", ha="center", fontsize=9, color=MUTED)
    ax.text(i + w / 2, (r * 1.25 if r else 1.3), f"{r:,}", ha="center", fontsize=9,
            color=INK, fontweight="bold")
ax.set_xticks(x, areas)
ax.set_ylabel("violations (log scale)")
ax.set_title("Violations by coverage area, detected vs residual (spesa.csv)", fontweight="bold", fontsize=13)
_bare(ax)
ax.tick_params(axis="x", length=0)
ax.legend(frameon=False, loc="upper right")
save(fig, "violations_by_area.png")


# 4. cells changed, by the stage that changed them
by_source = D["changes_summary"]["by_source"]
total = D["changes_summary"]["total_cells_changed"]
items = sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)
names = [k for k, _ in items]
counts = [v for _, v in items]

fig, ax = plt.subplots(figsize=(7.5, 3.4))
y = np.arange(len(names))[::-1]
ax.barh(y, counts, 0.6, color=ACCENT)
for yi, c in zip(y, counts):
    ax.text(c + total * 0.008, yi, f"{c:,}", va="center", fontsize=10, color=INK)
ax.set_yticks(y, names)
ax.set_xlabel("cells changed")
ax.set_xlim(0, max(counts) * 1.12)
ax.set_title(f"Where the {total:,} changed cells came from (spesa.csv)", fontweight="bold", fontsize=13)
_bare(ax, keep=("left",))
ax.tick_params(axis="y", length=0)
save(fig, "cells_changed_by_source.png")


# 5. per-stage timings; the stages that call a model are drawn dark
_LLM_STAGES = {
    "profiler", "semantic", "duplicate_column", "format_consistency",
    "anomaly_detector", "unified", "report_generator",
}
stages = sorted(T.items(), key=lambda kv: kv[1], reverse=True)
snames = [k for k, _ in stages]
secs = [v for _, v in stages]

fig, ax = plt.subplots(figsize=(7.4, 4.1))
y = np.arange(len(snames))[::-1]
ax.barh(y, secs, 0.6, color=[ACCENT if n in _LLM_STAGES else SOFT for n in snames])
for yi, s in zip(y, secs):
    ax.text(s + max(secs) * 0.012, yi, f"{s:.1f}s", va="center", fontsize=10, color=INK)
ax.set_yticks(y, snames)
ax.set_xlabel("seconds")
ax.set_xlim(0, max(secs) * 1.06)
ax.set_title(f"Where the {sum(secs):.0f}s run spends its time (dark = calls a model)",
             fontweight="bold", fontsize=13)
_bare(ax, keep=("left",))
ax.tick_params(axis="y", length=0)
save(fig, "stage_timings.png")


# 6. reliability across the three datasets, like-for-like
_DATASETS = [
    ("spesa", RUN / "spesa.json", "required"),
    ("attivazioniCessazioni", ROOT / "out" / "readme_attivazioni" / "attivazioniCessazioni.json", "required"),
    ("ritenuteSindacali", ROOT / "out" / "readme_ritenute" / "ritenuteSindacali.json", "held out"),
]


def _run_facts(path):
    q = json.loads(Path(path).read_text())["quality"]["like_for_like"]
    return q["before"]["score"], q["after"]["score"]


facts = [(name, _run_facts(p), tag) for name, p, tag in _DATASETS]

fig, ax = plt.subplots(figsize=(7.8, 3.5))
x = np.arange(len(facts))
w = 0.38
b = [f[1][0] for f in facts]
a = [f[1][1] for f in facts]
ax.bar(x - w / 2, b, w, color=SOFT, label="before remediation")
ax.bar(x + w / 2, a, w, color=ACCENT, label="as delivered")
for i, (bb, aa) in enumerate(zip(b, a)):
    ax.text(i - w / 2, bb + 0.004, f"{bb:.4f}", ha="center", fontsize=10, color=MUTED)
    ax.text(i + w / 2, aa + 0.004, f"{aa:.4f}", ha="center", fontsize=10, color=INK, fontweight="bold")
ax.set_xticks(x, [f"{n}\n({t})" for n, _, t in facts])
ax.set_ylim(0.80, max(a) + 0.03)
ax.set_ylabel("reliability, like-for-like")
ax.set_title("Reliability across the three datasets", fontweight="bold", fontsize=13)
_bare(ax)
ax.tick_params(axis="x", length=0)
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=2, frameon=False)
save(fig, "reliability_across_datasets.png")
