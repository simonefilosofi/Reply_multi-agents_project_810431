# Reply — Multi-Agent Data Quality System

A multi-agent pipeline for automated data quality analysis, built for the Reply/LUISS ML 2025/26 project. The system uses [Groq](https://console.groq.com) for LLM inference (free API).

---

## Requirements

- Python 3.9+
- A free [Groq API key](https://console.groq.com)

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd Reply_multi-agents_project_810431
```

### 2. Create and activate the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Add your Groq API key

Create a `.env` file in the project root:

```
GROQ_API_KEY=your_key_here
```

---

## Datasets

Located in `Datasets Reply-20260313/project_data_quality/`:

| File | Description |
|---|---|
| `attivazioniCessazioni.csv` | Employee activations and terminations |
| `spesa.csv` | Expenditure data |

---

## Project Structure

```
.
├── Datasets Reply-20260313/
│   └── project_data_quality/
│       ├── attivazioniCessazioni.csv
│       └── spesa.csv
├── state/
│   ├── pipeline_state.py       # shared memory passed between all agents
│   └── fingerprint_schema.py   # Pydantic schema for dataset profiling
├── agents/
│   ├── base_agent.py           # base class: Groq client, retry logic
│   ├── ingestion_agent.py      # Layer 0: loads CSV/JSON/Excel/Parquet
│   ├── profiler_agent.py       # Layer 0: classifies dataset semantically
│   ├── schema_agent.py         # Layer 1: checks column type consistency
│   ├── completeness_agent.py   # Layer 1: checks for missing values
│   ├── duplicate_agent.py      # Layer 1: detects duplicate rows and columns
│   └── anomaly_agent.py        # Layer 1: detects outliers and rare values
├── guidelines/
├── requirements.txt
└── README.md
```

---

## Pipeline (work in progress)

| Layer | Agents | Status |
|---|---|---|
| 0 — Intake | IngestionAgent, ProfilerAgent | done |
| 1 — Analysis | SchemaAgent, CompletenessAgent, DuplicateAgent, AnomalyAgent | done |
| 2 — Synthesis | SynthesisAgent | coming |
| 3 — Action | RemediationAgent, AutoFixAgent | coming |
| 4 — Output | ReportAgent | coming |

---

## Notes

- LLM inference runs via Groq (free tier) — no local GPU required.
- The `.venv/` directory is not tracked by git. Each contributor must create it locally.
- Never commit your `.env` file.
