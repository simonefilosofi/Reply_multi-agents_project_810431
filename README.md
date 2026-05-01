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

## Methods

### System architecture

The pipeline is a directed acyclic graph of 9 agents implemented with LangGraph. Each agent
reads from and writes to a shared `PipelineState` object, passing the cleaned dataset and a
per-column semantic payload downstream.

```
baseline_builder → profiler → semantic → nan_handler → duplicate_column
    → format_consistency → duplicate_row → report_generator
```


![Pipeline diagram](images/pipeline.png)

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

## Results

> **[TODO: fill in after running experiments on both datasets. All figures must be generated
> from `main.ipynb`.]**

### Canonical matching accuracy

| Method | spesa.csv | attivazioniCessazioni.csv |
|---|---|---|
| Name-only (baseline) | — | — |
| Embeddings retrieval (ours) | — | — |

### Placeholder detection

| Dataset | Precision | Recall |
|---|---|---|
| spesa.csv | — | — |
| attivazioniCessazioni.csv | — | — |

### End-to-end quality improvement

| Metric | Before | After | Δ |
|---|---|---|---|
| Total null cells | — | — | — |
| Format violations | — | — | — |
| Duplicate rows | — | — | — |
| Columns with correct dtype | — | — | — |

*(figures generated from main.ipynb — see `images/` folder)*

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
