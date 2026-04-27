# Cleanup Decisions Log

Append-only log of every conscious choice made under uncertainty during the
14-step refactor described in `Implementation Plan v2.md`. One entry per
decision, in chronological order. Each entry: the decision, the rationale,
the file/line where it lives.

---

## Step 1 — Project scaffolding

### D1.1 — Python pin held at `>=3.11,<3.13` despite 3.13 on user machine
- **File:** `pyproject.toml` (`project.requires-python`), `.python-version`.
- **Decision:** Keep the plan-mandated pin (`>=3.11,<3.13`) and ask the user to
  install Python 3.12 in a local venv. Do not silently widen the pin to allow
  3.13.
- **Rationale:** The plan anchors the toolchain to April 2026. Several pinned
  dependencies (notably `pydantic-ai>=1.85,<2.0` and `langgraph>=0.2,<1.0`)
  were validated against 3.11/3.12. Widening to 3.13 without verifying every
  pin would break the reproducibility contract the plan is supposed to
  guarantee. Surfaced at Confirmation Gate 1 so the user can decide whether to
  install 3.12 or amend the plan.

### D1.2 — Ruff configuration lives in `pyproject.toml` (no separate `ruff.toml`)
- **File:** `pyproject.toml`, sections `[tool.ruff]`, `[tool.ruff.lint]`,
  `[tool.ruff.format]`.
- **Decision:** Consolidate ruff configuration into `pyproject.toml` instead of
  emitting a standalone `ruff.toml` (the plan permits either).
- **Rationale:** Single source of truth for tool configuration; one fewer file
  to drift; matches the layout used for mypy and pytest configuration.

### D1.3 — `mypy` made non-blocking in CI for now
- **File:** `.github/workflows/ci.yml` (`mypy` step has
  `continue-on-error: true`).
- **Decision:** Allow mypy to report findings without failing the CI build for
  the duration of the refactor; the `[[tool.mypy.overrides]]` section already
  enforces strict typing on the *new* modules (`state_demo.config`,
  `state_demo.issues`, `state_demo.agent_names`, `state_demo.locale_it`,
  `state_demo.deliberation`).
- **Rationale:** The legacy code carries a large mypy backlog. The plan
  explicitly says this is expected and will be addressed step by step. Hard-
  failing CI on day one would block every gate. The strict overrides ensure
  new code never regresses. Coverage thresholds are formally enforced from
  Step 14 onward; mypy is treated similarly.

### D1.4 — Coverage source list includes both packages and the two top-level `tools*` modules
- **File:** `pyproject.toml` (`[tool.coverage.run]`).
- **Decision:** `source = ["state_demo", "agents_demo", "tools.py",
  "tools_code_validator.py"]`.
- **Rationale:** `tools.py` and `tools_code_validator.py` live at repo root,
  not inside a package, but the plan's coverage targets explicitly mention
  `tools.py` (≥80%). Listing the file path directly makes coverage visible in
  the report.

---

## Step 3 — Pydantic Issue discriminated union

### D3.1 — Multi-column issues keep `column: str` required and synthesise it from structured fields
- **File:** `state_demo/issues.py` (`DuplicateColumnsIssue._populate_column`,
  `DateOrderIssue._populate_column`, `DuplicateKeyIssue._populate_column`).
- **Decision:** `IssueBase.column` stays a required `str`. For the three
  multi-column subclasses (`DuplicateColumnsIssue`, `DateOrderIssue`,
  `DuplicateKeyIssue`) a `@model_validator(mode="before")` auto-fills `column`
  from `column_a` (or `key_columns[0]`) when callers omit it.
- **Rationale:** Every existing consumer in `tools.py`, the report, and the
  scoring layer assumes a single canonical `column` per issue (used for
  grouping, sorting, and per-column severity rollup). Making `column`
  Optional would force a defensive `if issue.column is not None` everywhere.
  The before-validator preserves the IssueBase invariant while still exposing
  the structured pair (`column_a` / `column_b`) the synthesis and remediation
  layers need to do their job.

### D3.2 — `_AnyIssue = (T1 | T2 | ... | T30)` parenthesised, then wrapped in `Annotated`
- **File:** `state_demo/issues.py` (the `_AnyIssue` block and the
  `Issue = Annotated[_AnyIssue, Field(discriminator="type")]` line).
- **Decision:** Spread the 30-member union across 30 lines inside parentheses
  and assign it to a private alias `_AnyIssue`, then form the public
  `Issue = Annotated[_AnyIssue, Field(discriminator="type")]` on a separate
  line.
- **Rationale:** `ruff --fix` rewrites `Union[...]` into the `|` syntax (UP007).
  On a 30-member union the resulting single-line expression blows past
  `line-length = 100` (E501). The CLAUDE.md "no comments" rule rules out
  `# noqa: E501`. The parenthesised multi-line form satisfies both lints
  structurally without suppressions.

### D3.3 — `IssueBase.source: AgentName | None` uses the closed Literal directly
- **File:** `state_demo/agent_names.py`, `state_demo/issues.py`
  (`IssueBase.source`).
- **Decision:** `source` is typed `AgentName | None`, where `AgentName` is the
  closed Literal of 13 agent identifiers. Detector-side construction may leave
  it `None`; the routing layer stamps it before the issue is appended to
  `PipelineState.issues`. Any redundant `AGENT_NAMES` string-list copy living
  in `state_demo/constants.py` will be removed in Step 4 to prevent drift.
- **Rationale:** A typo in an agent name now surfaces at type-check time
  rather than at run time, and `model_json_schema()` advertises the closed
  enum to any downstream consumer (PydanticAI structured outputs, the report).
