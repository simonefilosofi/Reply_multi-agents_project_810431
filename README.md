# Agents for Data Quality — NoiPA

**Team members**: Allam Eliya, Cervelli Mattia, Filosofi Simone  
**Captain**: Filosofi Simone — student ID: 810431  

---

## Introduction

NoiPA is the digital platform of the Ministero dell'Economia e delle Finanze managing
salaries, timesheets, and tax/social-security obligations for Italian Public Administration
employees. It periodically receives datasets from heterogeneous sources (CSV, JSON, DBs)
containing demographic, economic, and HR data. Currently, validation of these datasets is
manual or nonexistent, creating a bottleneck for data reliability.

In this project we built a **multi-agent data quality system** that takes a raw CSV dataset,
automatically detects and fixes data quality issues, and produces a structured quality report
including anomalies, correction suggestions, and a reliability score. The system is
implemented as a LangGraph pipeline of specialised agents, each responsible for a distinct
data quality dimension: schema validation, completeness analysis, consistency checking,
anomaly detection and remediation.


---

## Repository contents

A one-pass map of every file in the repo, so a reviewer can locate any component in seconds.

### Top-level entry points and deliverables

- `main.ipynb` — The single deliverable notebook. Walks through every pipeline agent on `attivazioniCessazioni.csv` with alternating markdown / code cells; each agent section embeds its corresponding `prompts/*.md` inline so the notebook is self-contained.
- `app.py` — Streamlit harness exposing the pipeline behind an interactive approval gate where a reviewer can Accept, Reject, or Edit-with-feedback each remediation proposal before it is applied.
- `graph.py` — LangGraph DAG wiring the nine canonical pipeline agents (`baseline_builder` → `profiler` → `semantic` → `nan_handler` → `duplicate_column` → `classification` → `format_consistency` → `duplicate_row` → `report_generator`).
- `unified_agent.py` — Stand-alone E2B-cloud sandbox prototype that takes approved fixes and runs LLM-generated `clean_data(df)` code in an isolated container; kept as a forward-looking experiment for sandboxed remediation.
- `attivazioniCessazioni.pdf` — Sample report produced by `agents/report_generator.py` on `attivazioniCessazioni.csv`, committed as an example deliverable.
- `README.md` — This file.

### Pipeline core types

- `state.py` — Defines `PipelineState`, the single Pydantic model every agent reads from and writes to (dataset, baseline, payload, validation reports, anomaly reports, proposed fixes, ...).
- `models.py` — All Pydantic data models exchanged across the pipeline (`BaselineFile`, `ColumnPayload`, `ValidationReport`, `FixProposal`, `AnomalyReport`, ...).

### Agents (`agents/`)

- `agents/baseline_builder.py` — Loads `noipa_schema_registry.json`, resolves every `$ref` against `shared_column_definitions`, and validates the result into a `BaselineFile`. Pure-Python, no LLM call.
- `agents/profiler.py` — Asks `gpt-4o-mini` to identify the dataset's NoiPA domain and primary language by matching the input column signature against the per-domain signatures derived from the baseline.
- `agents/semantic.py` — Per-column enrichment that combines deterministic name matching, embeddings retrieval against `column_descriptions.json`, and an LLM verdict to produce a `ColumnPayload` with description, dtype, placeholders, related columns, target casing, and canonical hint.
- `agents/nan_handler.py` — Replaces disguised NaN tokens (the placeholder list inferred by the Semantic agent) with `pd.NA`, then flags non-nullable canonical columns whose NaN count is still positive.
- `agents/duplicate_column.py` — Groups columns by hashed-value identity, asks an LLM to elect the most descriptive surface name within each group, and backfills NaNs from the dropped sibling.
- `agents/classification.py` — Produces a snake_case normalised name and short description for each surviving column; currently a deterministic stub that the graph keeps in place for future LLM enrichment.
- `agents/format_consistency.py` — Picks a `FormatSpec` per column (from baseline or via LLM inference), validates every value against it, and asks an LLM to suggest per-value corrections for the Unified agent to consider.
- `agents/anomaly_detector.py` — Flags numeric outliers (IQR rule) and rare categorical values (frequency + count threshold), then asks `gpt-4o-mini` to attach a one-sentence explanatory comment per anomalous column.
- `agents/unified.py` — Groups columns by their related-columns transitive closure, aggregates upstream violations, and asks an LLM to emit `FixProposal` objects (description + Python snippet) covering every input violation; never executes code itself.
- `agents/duplicate_row.py` — Drops exact duplicate rows via `drop_duplicates()` as the final cleaning step, after column-level normalisations have run.
- `agents/report_generator.py` — Builds a structured payload from the final `PipelineState` and uses `gpt-4o-mini` plus `fpdf2` to produce a five-section narrative PDF report.
- `agents/__init__.py` — Empty package marker.

### Tools (`tools/`)

Reusable building blocks used by multiple agents.

- `tools/baseline_accessors.py` — Projection helpers (e.g. `find_spec_by_hint`, `domain_signatures`) exposing slice views of the resolved `BaselineFile` so agents do not leak the full structure into their prompts.
- `tools/match_canonical.py` — Programmatic name-match cascade (exact → accent-and-case-normalised → fuzzy) plus a compact format-summary helper, consumed by the Semantic and Unified agents.
- `tools/retrieve_canonical.py` — Embeddings-based retriever that embeds `column_descriptions.json` once with `text-embedding-3-small`, caches the matrix to `column_descriptions.embeddings.pkl`, and ranks candidates by cosine similarity boosted with sample-overlap and dtype-agreement signals.
- `tools/infer_and_validate_dtype.py` — Pandas-driven dtype inference that reconciles the LLM's dtype suggestion with the actual sample before casting.
- `tools/detect_placeholders.py` — Replaces values matching a payload-derived placeholder list with NaN; used internally by the NaN Handler.
- `tools/infer_format_spec.py` — LLM call that proposes a `FormatSpec` (regex / enum / range / date) for columns with no canonical match.
- `tools/validate_format.py` — Runs a `FormatSpec` over a column and emits a `FormatViolation` for every failing value, with uniform `expected_pattern` strings across spec types.
- `tools/correct_violations.py` — LLM call that takes the unique offending values of a column plus its neighborhood and returns a `{value -> corrected_value | null}` map for the Unified agent to apply.
- `tools/normalize_date_format.py` — Coerces date-like columns to a consistent strftime format dictated by the baseline.
- `tools/normalize_entity_format.py` — Standardises strings representing organisation / entity names (whitespace, casing, common abbreviations).
- `tools/apply_casing.py` — Applies the `target_casing` directive from a `ColumnPayload` to a string column.
- `tools/cluster_by_domain.py` — Groups multiple input dataframes by thematic NoiPA domain via metadata or LLM classification (used when batch-processing several files).
- `tools/extract_column_schema.py` — Extracts column names, dtypes, and format patterns from sample data and serialises them in the baseline-compatible shape.
- `tools/hash_column_values.py` — Produces a deterministic hash of a column's full sorted value set; the identity primitive behind the Duplicate-Column agent.
- `tools/scrape_pa_datasets.py` — Fetches and downloads datasets from the Italian PA open-data portal (`dati.gov.it`); used offline to bootstrap the canonical knowledge base.
- `tools/__init__.py` — Empty package marker.

### Utilities (`utils/`)

- `utils/prompts.py` — `load_prompt(name)` helper that reads `prompts/<name>.md` from disk; the single way every agent fetches its system prompt at runtime.
- `utils/__init__.py` — Empty package marker.

### Prompts (`prompts/`)

System prompts loaded by `utils.prompts.load_prompt()`. Files marked *(reference)* exist as design-time documentation for nodes that are currently deterministic and do not load a prompt at runtime.

- `prompts/profiler.md` — Domain and language detection prompt for `agents/profiler.py`.
- `prompts/semantic.md` — Canonical-match decision prompt for `agents/semantic.py`, called once the embedding shortlist has been built.
- `prompts/semantic_describe.md` — Batched first-pass prompt that asks `gpt-4o-mini` for a one-sentence factual description of every column at once.
- `prompts/duplicate_column.md` — Canonical-name election prompt for `agents/duplicate_column.py`.
- `prompts/infer_format_spec.md` — System prompt for `tools/infer_format_spec.py` (proposes a `FormatSpec` from a value sample).
- `prompts/correct_violations.md` — System prompt for `tools/correct_violations.py` (proposes per-value corrections).
- `prompts/anomaly_detector.md` — Comment-generation prompt for `agents/anomaly_detector.py`.
- `prompts/unified.md` — `FixProposal` generation prompt for `agents/unified.py`.
- `prompts/report_generator.md` — Five-section narrative prompt for `agents/report_generator.py`.
- `prompts/format_consistency.md` *(reference)* — Design-time prompt for `agents/format_consistency.py`; the agent currently delegates to its sub-tools' prompts.
- `prompts/baseline_builder.md` *(reference)* — Schema-registry shape reference; the builder itself is deterministic.
- `prompts/classification.md` *(reference)* — Reference for the Classification agent's planned LLM call.
- `prompts/nan_handler.md` *(reference)* — Reference for the NaN handler; the runtime implementation is deterministic.
- `prompts/impute_gate.md` *(reference)* — Forward-looking reference for an imputation-gating agent that decides whether each missing cell should be imputed or left as NaN.

### Knowledge base and generated artefacts

- `noipa_schema_registry.json` — Hand-authored canonical NoiPA schema covering 4 domains (`Amministrati`, `Amministrazioni`, `Rapporti_di_lavoro`, `Trattamento_economico`), 12 shared column definitions reused via `$ref`, and 143 dataset-specific columns; the source of truth for every validation rule in the pipeline.
- `baseline.json` — Compiled, fully-dereferenced version of the registry produced at runtime by `agents/baseline_builder.py`; consumed by every downstream agent.
- `column_descriptions.json` — Catalogue of 54 canonical NoiPA columns (name, description, sample values, dtype) used as the retrieval corpus for the Semantic agent.
- `column_descriptions.embeddings.pkl` — On-disk cache of the 54×1536 embedding matrix for `column_descriptions.json`, regenerated automatically by `tools/retrieve_canonical.py` when the catalog changes.
- `payload.json` — Scratch file used during development to inspect the `ColumnPayload` list emitted by the Semantic agent; not loaded at runtime.

### Data (`Datasets-Reply-20260313/project_data_quality/`)

- `attivazioniCessazioni.csv` — One of the two NoiPA test datasets used in the experiments; tracks employment activations and terminations.
- `spesa.csv` — The second NoiPA test dataset; tracks personnel expense data.

### Project setup

- `requirements.txt` — Pinned Python dependencies covering `pandas`, `numpy`, `pydantic`, `langgraph`, `langchain-openai`, `openai`, `streamlit`, `fpdf2`, `e2b-code-interpreter`, plus a few extras kept around for the JSON / Excel / Parquet ingestion paths the brief mentions.
- `.env` — Local environment file holding `OPENAI_API_KEY`; loaded by `dotenv.load_dotenv()` at the top of every entry point.
- `.gitignore` — Excludes the `.env/` directory and Python bytecode caches.

### Reference material (`guidelines/`)

- `guidelines/Reply_projects.pdf` — The Reply-issued project brief defining deliverable expectations and the six data-quality dimensions.
- `guidelines/ML Projects general info.docx.pdf` — Course-issued guidelines for ML project deliverables (notebook structure, README expectations, results-section conventions).

---

## Methods

### System architecture

The pipeline is a directed acyclic graph of 9 agents implemented with LangGraph. Each agent
reads from and writes to a shared `PipelineState` object, passing the cleaned dataset and a
per-column semantic payload downstream.

```
baseline_builder → profiler → semantic → nan_handler → duplicate_column
    → format_consistency → duplicate_row → report_generator
```



### The two knowledge-base files

The pipeline is grounded in two manually curated JSON files that together form a
semi-RAG knowledge base about NoiPA's canonical data model.

**`noipa_schema_registry.json` → compiled into `baseline.json`**  
A hand-authored schema registry covering 4 NoiPA domains (*Amministrati*, *Amministrazioni*,
*Rapporti di lavoro*, *Trattamento economico*), 143 dataset columns, and 12 shared column
definitions reused across datasets via `$ref` pointers. For each column it records: `dtype`,
`format` (enum of allowed values, regex pattern, or numeric range), `case_convention`,
`is_nullable`, and a `canonical_id` linking it to a shared definition. It also encodes global
naming conventions, k-anonymity floors, and domain-level observations. At runtime,
`baseline_builder` resolves all `$ref` pointers and compiles the registry into a validated
`BaselineFile` Pydantic object that every downstream agent reads.

**`column_descriptions.json`**  
A separate catalog of 54 canonical NoiPA columns, each entry containing: `column_name`,
`description` (a one-sentence domain explanation in English), `sample` (representative real
values), and `dtype`. This file was built to support semantic retrieval — names alone are
insufficient because incoming datasets use synonyms, abbreviations, or Italian variants.
At startup, `retrieve_canonical.py` embeds each entry's `name + description + samples` string
using `text-embedding-3-small` and caches the resulting 54×1536 matrix to
`column_descriptions.embeddings.pkl`. This offline index is the retrieval backbone of the
semantic agent.

Together the two files encode *what* the data should look like (`noipa_schema_registry.json`)
and *how to recognise it semantically* (`column_descriptions.json`). No agent invents
canonical knowledge — every validation decision traces back to one of these two sources.

### Agent descriptions

**`baseline_builder`**  
Reads `noipa_schema_registry.json`, resolves all `$ref` entries against the
`shared_column_definitions` block, and validates the full structure into a `BaselineFile`
Pydantic model. Writes the resolved result to `baseline.json` so downstream agents have a
single, fully-dereferenced schema object to query. This is a pure Python step — no LLM call.

**`profiler`**  
Builds a hierarchical signature map of the baseline (domain → dataset → column names) and
sends it alongside the input dataset's column names and 5-row samples to `gpt-4o-mini`. The
LLM returns the most likely NoiPA domain and primary language. This detection gates how
subsequent agents interpret ambiguous columns — for example, a column named `rata` means
something different in `spesa` vs. `attivazioniCessazioni`.

**`semantic`** *(core agent — semi-RAG)*  
The most complex agent, running four sub-steps per column:

1. **Batch description pass**: sends all columns (name + dtype + 5 samples) to `gpt-4o-mini`
   in a single call and gets back a one-sentence factual description for each. This description
   is the query text for retrieval — it captures meaning rather than just name.

2. **Embedding retrieval**: for each column, concatenates `name + description + samples` into
   a query string, embeds it with `text-embedding-3-small`, and scores all 54 entries in
   `column_descriptions.json` by cosine similarity. The score is boosted by two signals:
   sample-value overlap (fraction of input samples that appear in the catalog entry's samples)
   and dtype agreement (+0.1 bonus). Returns the top-5 candidates.

3. **LLM verdict**: sends the column's name, dtype, 30-row sample, placeholder candidates,
   `canonical_suggestion` (from name-based fallback), and the top-5 retrieval candidates to
   `gpt-4o-mini`. The LLM confirms or rejects each candidate by comparing descriptions and
   sample vocabularies, and returns: `canonical_match`, `dtype`, `column_meaning`,
   `placeholders`, `related_columns`, `target_casing`.

4. **Validation and dtype casting**: the returned `canonical_match` is validated by looking it
   up in `column_descriptions.json` — if it is not a real entry, it is discarded and replaced
   with the sentinel `"NaN"`. The resolved canonical dtype (from the registry) overrides the
   LLM dtype suggestion. The column is then cast in-place using pandas.

**`nan_handler`**  
Iterates over each column's `placeholders` list (produced by the semantic agent) and replaces
matching values with `pd.NA` using exact and case-insensitive string comparison. Then checks
each column whose `canonical_hint` resolves to a `is_nullable=False` spec: if any nulls
remain after replacement, a `ValidationReport` violation is emitted. This agent applies no
LLM call — the intelligence was already applied upstream in the semantic agent.

**`duplicate_column`**  
Computes pairwise column similarity (value-overlap Jaccard at 0.80 threshold) to find groups
of near-duplicate columns. Within each group, elects the data survivor as the column with
fewest nulls, then backfills its missing values from the other group members. Calls
`gpt-4o-mini` once per group to elect the canonical output name (the name most consistent
with the NoiPA registry and the detected domain). Drops all non-survivors and records a
`DuplicateResolution` entry per group.

**`format_consistency`**  
For each surviving column with a resolved `canonical_hint`, retrieves the column's `format`
spec from the baseline and validates every value against it: enum specs check membership,
regex specs test pattern match, range specs check numeric bounds. Each violation is recorded
as a `FormatViolation` with the row index and observed value. Also applies two normalisation
tools (`normalize_date_format`, `normalize_entity_format`) to correct recoverable formatting
inconsistencies before flagging them as violations.

**`duplicate_row`**  
Drops exact duplicate rows using pandas `drop_duplicates()` as a final cleaning step after
all column-level operations are complete. Runs last among the cleaning agents so that
column renaming, backfilling, and format normalisation have already been applied — deduplication
on the clean data is more precise than on the raw data.

**`report_generator`**  
Builds a structured payload from the final pipeline state — dataset shape, per-column null
percentages, the semantic payload (column meanings, dtypes, placeholders), duplicate
resolutions, and validation violations — and sends it to `gpt-4o-mini` to produce five
narrative sections: executive summary, dataset overview, quality findings, actions taken, and
recommendations. Renders the result to a PDF using `fpdf2`.

### Key design decisions

**Why a semi-RAG approach instead of a pure LLM call?**  
Early versions asked the LLM to pick a canonical match from the full 54-entry catalog in a
single prompt. This consistently failed on columns whose names differed from the canonical id
(synonyms, abbreviations, Italian/English variants). The failure mode was silent — the LLM
would return a plausible-sounding but wrong canonical id, propagating incorrect dtype and
format expectations to every downstream agent. Moreover we wanted to have an official noiPA 'book' to use as reference, so that for shared columns or similar ones we could know for sure what dtype or format to choose in order to fix the dataset. 

The semi-RAG approach splits the problem: embeddings retrieve semantically close candidates
cheaply and deterministically; the LLM only adjudicates among the top-5 shortlist. The
retrieval score combines three signals — description cosine similarity (captures meaning),
sample-value overlap (captures actual data), dtype agreement (coarse type filter) — so the
top-1 candidate is almost always the right column before the LLM even sees it.

**Why two separate knowledge-base files?**  
`noipa_schema_registry.json` encodes structural constraints (what values are valid, what dtype
is required, whether nulls are allowed). `column_descriptions.json` encodes semantic
fingerprints (what the column means, what it looks like). These are different concerns: the
schema is used for validation; the descriptions are used for retrieval. Merging them into one
file would couple retrieval quality to schema maintenance and make the catalog harder to extend
independently.

**Why pre-generate column descriptions offline rather than asking the LLM at query time?**  
Embedding the catalog once and caching the matrix to disk costs one API call at first run.
Every subsequent pipeline execution retrieves from the cached index in microseconds, regardless
of dataset size. Generating descriptions on the fly would require an LLM call per catalog
entry per pipeline run — 54 extra calls per execution with no benefit, since the catalog does
not change between runs.

**Why LangGraph?**  
Each agent has a single responsibility and mutates a different part of the shared
`PipelineState`. LangGraph's explicit graph makes the execution order auditable, allows agents
to be replaced or parallelised independently, and keeps the orchestration logic separate from
the agent logic.

### Environment

Python 3.11. Key dependencies:

```
langchain-openai
langgraph
openai
pandas
pydantic
fpdf2
streamlit
numpy
scikit-learn   # for anomaly detection
```

To recreate:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in a `.env` file at the project root. The pipeline uses `gpt-4o-mini`
for all LLM calls and `text-embedding-3-small` for canonical retrieval. The embedding index
for `column_descriptions.json` is cached to disk on first run.

---

## Experimental Design

The core contribution of this project is a multi-agent pipeline that automatically identifies
and fixes data quality issues in NoiPA datasets. We validate it through three experiments.

### Experiment 1 — Canonical matching accuracy

**Purpose**: measure how often the semantic agent assigns the correct `canonical_hint` to an
input column.

**Baseline**: name-only programmatic matching (exact → accent-normalised → difflib fuzzy at
0.85 cutoff), which was the original approach.

**Method**: manually label the ground-truth canonical id for each column in both test datasets
(`spesa.csv` and `attivazioniCessazioni.csv`). Compare the fraction of correct canonical_hint
assignments between baseline (name-only) and the embeddings-based retrieval approach.

**Metric**: canonical match accuracy = correctly matched columns / total columns.

### Experiment 2 — Placeholder detection precision and recall

**Purpose**: measure how accurately the pipeline detects disguised NaN tokens.

**Baseline**: pandas `isnull()` count only — no placeholder detection.

**Method**: manually annotate a sample of rows in both datasets with known placeholder values.
Compare detected placeholders against the annotation.

**Metrics**: precision = true placeholder detections / total detections; recall = true
placeholder detections / total annotated placeholders.

### Experiment 3 — End-to-end quality improvement

**Purpose**: demonstrate that the full pipeline improves dataset quality in measurable terms
across both datasets.

**Baseline**: raw CSV with no processing.

**Method**: run the full pipeline on `spesa.csv` and `attivazioniCessazioni.csv`. Measure
before/after on: (a) null count per column, (b) format violation count, (c) duplicate row
count, (d) columns with correct dtype.

**Metrics**: absolute reduction in nulls, violations, and duplicates; dtype correctness rate.

---


## Conclusions

This project shows that a multi-agent LLM pipeline can automate the majority of data quality
tasks that NoiPA analysts currently perform manually. The key takeaway is that grounding LLM
decisions in a curated canonical schema registry — via embedding retrieval rather than name
matching — substantially improves the reliability of downstream validation: format checks and
dtype casting only produce meaningful results when the canonical match is correct.

**Limitations and open questions**:

- **NaN imputation coverage is limited by data redundancy.** The unanimity-based imputation
  only fills cells where another row with the same related-column value exists and all such
  rows agree on the target value. In sparse or highly granular datasets, most nulls remain
  unfilled. A more aggressive strategy (mode-based fill, LLM-guided interpolation) would
  improve coverage at the cost of potentially inventing values.

- **Anomaly detection thresholds are heuristic.** IQR and frequency-based cutoffs are
  starting points; the right thresholds depend on each column's distribution and the
  operational tolerance for false positives. Future work could learn domain-specific
  thresholds from labelled historical data.

- **Evaluation depends on manual annotation.** A proper ground-truth evaluation requires
  human-labelled datasets, which are expensive to produce. Future work could use synthetic
  data injection (deliberately inserting known errors) as a more scalable evaluation approach.

- **The pipeline is sequential.** Each agent waits for the previous one to finish.
  LangGraph supports parallelism; agents that operate on independent column subsets
  (e.g. format_consistency and duplicate_row) could run concurrently to reduce latency on
  wide datasets.

