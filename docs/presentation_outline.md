# Presentation outline (12 slides)

A markdown skeleton for the project presentation. Each slide carries a
title, the bullet content, and a `Reference:` line pointing to the
concrete code artefact that backs the claim — so the slides can be
fact-checked against the repo.

---

## Slide 1 — Title

- **NoiPA — Multi-Agent Data Quality**
- Subtitle: *Detect, fix, and explain quality issues in Italian Public
  Administration payroll data with a Supervisor-style agent system.*
- Authors / affiliation block.
- Reference: `README.md` (problem statement); `CLAUDE.md` (project
  context).

## Slide 2 — NoiPA context

- NoiPA = Servizi PA a Persone PA — MEF / Italian Public
  Administration payroll & HR.
- Datasets are heterogeneous: schema drift, locale-specific
  placeholders, comma-decimals, currency-suffixed amounts.
- Reliability of the underlying data drives downstream payments and
  reporting accuracy.
- Reference: `data/examples/README.md` (schema), the
  `Datasets-Reply-20260313/` real samples.

## Slide 3 — The data quality challenge

- Show 6–8 representative rows from `dirty_noipa_sample.csv` with
  highlights: `1.234,56` comma-decimals, `€2500` currency suffix,
  `IRPEF` / `irpef` / `Irpef` case mixing, `N.D.` / `n.c.`
  placeholders, `202413` invalid month code, `Rata 2024` free text.
- Frame the question: *can we detect, classify, fix and explain
  these automatically?*
- Reference: `data/examples/dirty_noipa_sample.csv` and
  `data/examples/_generate.py`.

## Slide 4 — Multi-agent architecture

- Embed the layer diagram from `docs/pipeline.svg`:
  Bootstrap → Detection ×6 (parallel) → Synthesis → Remediation →
  CodeValidator (conditional) → Reporting.
- 12 agents total; Supervisor pattern (tool-calling style) on
  LangGraph; typed LLM I/O via PydanticAI.
- Reference: `docs/architecture.md`, `agents_demo/_graph.py`,
  `docs/pipeline.svg`.

## Slide 5 — Live demo flow

- Upload `dirty_noipa_sample.csv` to the Streamlit dashboard.
- Walk through: live agent status table, prioritised issues,
  remediation summary, deliberation log, generated fixes (LLM code
  shown with syntax highlight), reliability score before/after,
  charts and JSON export.
- Reference: `app_demo.py`, screenshots in
  `docs/architecture.md`.

## Slide 6 — Reliability score deep-dive

- Five dimensions, weighted: Schema (20), Completeness (25),
  Uniqueness (20), Consistency (20), Anomaly Freedom (15).
- Score = weighted mean × 100 ∈ [0, 100].
- Trajectory: scored at `post_synthesis`, `post_remediation`,
  `post_code_validator` to make pipeline progress visible.
- Reference: `state_demo/scoring.py::compute_reliability_score`,
  `tools.py::chart_dimension_trajectory`.

## Slide 7 — The CodeValidator self-healing loop

- Why: residual gap issues that no fixed strategy covers (e.g.,
  Italian-specific text normalisation).
- How: LLM filter → LLM fix function → AST guard → Docker sandbox
  (read-only, network-off, dropped caps, nobody UID) → safety
  guards → apply or human review.
- Defence in depth: AST guard + restricted builtins + sandbox +
  post-fix safety guards (quantitative cap, type-drift, LLM review).
- Reference: `agents_demo/code_validator_agent.py`,
  `tools_code_validator.py`, `tools.py::validate_generated_code`,
  cleanup decisions D12.1–D12.6.

## Slide 8 — Italian-locale handling (differentiator)

- Comma-decimal auto-fix (`1.234,56` → `1234.56`) gated by a regression
  guard.
- Currency-symbol stripping while preserving sign and decimal precision.
- Italian month abbreviations (`gen` … `dic`) including the `mar`
  collision with English March; full names mapped via
  `MONTH_FULL_IT_EN`.
- Italian placeholder vocabulary in `state_demo/locale_it.py`
  (`sconosciuto`, `non disponibile`, `da verificare`, …).
- Reference: `state_demo/locale_it.py`, `tools.py` locale fixes,
  `tests/tools/test_tools.py`.

## Slide 9 — Deliberation example

- Pick one concrete `DeliberationOutcome` from
  `state.deliberation_log` after the demo run.
- Show the contested issue (e.g., outlier on `delta_amount` vs
  domain-negative-values constraint), the two specialist votes
  (anomaly: keep@0.8; constraint: drop@0.7), and the supervisor's
  tie-break.
- Reference: `agents_demo/synthesis_agent.py`,
  `state_demo/deliberation.py`,
  `tests/integration/test_deliberation_e2e.py`.

## Slide 10 — Reliability uplift on the two test datasets

- Side-by-side table: before / after reliability score for
  `clean_noipa_sample.csv` and `dirty_noipa_sample.csv`, plus
  number of issues detected and fixes applied.
- Show the two before/after completeness heatmaps and the
  issue-resolution Sankey.
- Reference: `scripts/smoke_test.py`,
  `tools.py::chart_issue_resolution_sankey`,
  `tools.py::chart_completeness_heatmap_before_after`.

## Slide 11 — Limitations and future work

- Italian-locale heuristics underperform on non-Italian data.
- Reliability score is opinionated, not an industry-standard metric.
- Profiler is LLM-driven and can drift between runs even on identical
  inputs (mitigated by the hallucination guard, not eliminated).
- Sandbox falls back to AST-guard-only on Windows.
- No persistent cross-run memory — every run is independent.
- Future: persistent memory layer; multi-table referential integrity;
  domain-specific score weighting.
- Reference: `README.md` Limitations section, cleanup decisions
  D8.1–D8.4 and D12.1–D12.6.

## Slide 12 — Q&A

- Repo: link to GitHub.
- Hand-off artefacts: `Implementation Plan v2.md`, `CLAUDE.md`,
  `docs/architecture.md`, `docs/cleanup_decisions.md`.
- Acknowledgements: MEF / NoiPA, Anthropic, OpenAI, the LangGraph
  and PydanticAI maintainers.
- Reference: top-level `README.md`.
