# Reply — Multi-Agent Data Quality System

A multi-agent pipeline for automated data quality analysis, built for the Reply/LUISS ML 2025/26 project. The system uses locally running LLMs via [Ollama](https://ollama.com) and is orchestrated with [LangGraph](https://langchain-ai.github.io/langgraph/).

---

## Requirements

- Python 3.9+
- [Ollama](https://ollama.com) installed and running locally

---

## Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd Reply_multi-agents_project_810431
```

### 2. Install Ollama and pull a model

Download Ollama from [ollama.com](https://ollama.com) and install it, then pull the model used by the pipeline:

```bash
ollama pull llama3
```

Make sure the Ollama server is running (it starts automatically on install, or run `ollama serve`).

### 3. Create and activate the virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

---

## Datasets

The datasets are located in `Datasets Reply-20260313/project_data_quality/`:

| File | Description |
|---|---|
| `attivazioniCessazioni.csv` | Employee activations and terminations |
| `spesa.csv` | Expenditure data |

---

## Project Structure right now

```
.
├── Datasets Reply-20260313/
│   └── project_data_quality/
│       ├── attivazioniCessazioni.csv
│       └── spesa.csv
├── guidelines/
├── .venv/                  # virtual environment (not tracked)
├── requirements.txt
└── README.md
```

---

## Usage

> Coming soon as agents are implemented.

---

## Notes

- All LLM inference runs **locally** via Ollama — no API keys required.
- The `.venv/` directory is not tracked by git. Each contributor must create it locally following the steps above.