# Duplicate Column Agent Prompt

## Task
Two or more columns in the dataset have identical value sets (same hash).
Choose which column name to retain as the canonical one and which to drop.

## Input
- `duplicate_group`: list of column names that are duplicates
- `domain`: dataset domain
- `baseline_columns`: list of column names present in the baseline for this domain

## Output
Return a JSON object:
```json
{
  "canonical_name": "<chosen column name>",
  "dropped": ["<other column names>"],
  "rationale": "<one sentence>"
}
```

## Guidelines
- Prefer names that appear in the baseline for the dataset's domain.
- Prefer more descriptive or conventional names over cryptic abbreviations.
- If a baseline match exists, always prefer it.
