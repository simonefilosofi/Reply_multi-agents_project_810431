# NoiPA — Multi-Agent Data Quality Pipeline

A Supervisor-style multi-agent system that ingests Italian Public Administration (NoiPA) datasets, detects quality issues across six dimensions (schema, completeness, consistency, anomaly, constraints, duplicates), automatically remediates what it can, and produces a multi-dimensional reliability score before and after remediation.

> Status: **work in progress**. The repository is being refactored according to the 14-step roadmap in [`Implementation Plan v2.md`](./Implementation%20Plan%20v2.md). Final README content lands in Step 14.

---

## Quickstart

```bash
git clone <repo-url>
cd Reply_multi-agents_project_810431
python -m venv .venv && source .venv/Scripts/activate   # Windows; use bin/activate on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env                                    # add your ANTHROPIC_API_KEY / OPENAI_API_KEY
streamlit run app_demo.py
```

---

## Repository layout (target, see `CLAUDE.md`)

```
state_demo/      # configuration, typed issue model, locale registry, pipeline state
agents_demo/    # one file per agent + LangGraph wiring + PydanticAI clients
tools.py        # stateless detection / fix functions
tools_code_validator.py  # sandbox utilities for the code validator
app_demo.py     # Streamlit dashboard
data/examples/  # synthetic Italian-locale demo datasets
tests/          # pytest harness
docs/           # architecture diagram, presentation outline, decision log
```

---

## Tech stack (April 2026)

LangGraph (orchestration) + PydanticAI (typed LLM I/O), Pydantic 2 discriminated unions for issues, Pandas 2.x dataframes, Streamlit UI, Docker-based sandbox for LLM-generated fixes (with a hardened-subprocess fallback).

Default models: Anthropic `claude-sonnet-4-6` (smart) and `claude-haiku-4-5-20251001` (fast); OpenAI `gpt-5.4` / `gpt-5.4-mini` as fallbacks. Pinned versions live in [`pyproject.toml`](./pyproject.toml).

---

## Plan and contract

- The 14-step roadmap is in [`Implementation Plan v2.md`](./Implementation%20Plan%20v2.md).
- Operating contract for any AI agent working on this repo is in [`CLAUDE.md`](./CLAUDE.md).
- Decisions taken under uncertainty are appended to `docs/cleanup_decisions.md` as the project advances.

---

## Datasets

Real NoiPA samples live in [`Datasets-Reply-20260313/project_data_quality/`](./Datasets-Reply-20260313/project_data_quality/) and are not modified by the pipeline. Synthetic Italian-locale demo CSVs (clean, dirty, large) are produced under `data/examples/` from Step 5 onwards.
