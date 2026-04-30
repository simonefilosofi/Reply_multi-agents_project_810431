# Classification Agent Prompt

## Task
For a single surviving column, produce a normalized column name and a short human-readable description.

## Input
- `column_name`: original column name
- `domain`: dataset domain
- `dtype`: pandas dtype string
- `sample`: list of sample values
- `baseline_columns`: list of canonical column names from the baseline for this domain

## Output
Return a JSON object:
```json
{
  "normalized_name": "snake_case_name",
  "description": "One sentence describing what this column represents."
}
```

## Guidelines
- `normalized_name` must be lowercase snake_case.
- If a close match exists in `baseline_columns`, align the normalized name to it.
- The description should reference the domain context and be concise (≤ 15 words).
