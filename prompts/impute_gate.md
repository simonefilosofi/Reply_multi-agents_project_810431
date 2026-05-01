# Imputation-Gate Agent Prompt

## Task
Decide which candidate columns can SAFELY be used to impute missing values in a target column
via groupby-and-unanimity. Only return candidates whose relationship to the target is a
**deterministic functional dependency**: knowing the candidate's value uniquely determines
the target's value.

## Input
A JSON object with:
- `target`: `{name, description, samples}` — the column we want to impute.
- `candidates`: a list of `{name, description, samples}` — columns the semantic agent
  flagged as related to `target`.

## Output
```json
{
  "functional_keys": ["<candidate name>", ...],
  "rationale": "<one sentence>"
}
```

`functional_keys` MUST be a subset of the candidate names. Empty list is valid and is the
correct answer when no candidate is a true functional dependency.

## Guidelines
Include a candidate when knowing it determines the target. Examples:
- A geographic parent: `provincia` → `regione`, `comune` → `provincia`.
- A code that maps to its label: `cod_ente` → `ente`, `cod_imposta` → `imposta`.
- An identifier that maps to a fixed attribute.

EXCLUDE candidates where the relationship is correlation, not determination:
- Paired bounds (`eta_min` ↔ `eta_max`, `data_inizio` ↔ `data_fine`) — same group can have
  many target values.
- Aggregation pairs (`importo` ↔ `numero_cedolini`) — independent measurements.
- Worker/employer mirrors (`importo_lavoratore` ↔ `importo_datore`) — correlated, not
  deterministic.
- Any pair where the same candidate value plausibly co-occurs with multiple distinct
  target values.

When in doubt, exclude. A wrong include silently invents data; a wrong exclude only
leaves a NaN that downstream agents will flag.
