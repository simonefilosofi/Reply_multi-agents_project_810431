# Semantic Agent Prompt

## Task
Analyze a single dataset column and produce a structured semantic payload.

## Input
- `column_name`: string
- `domain`: detected domain of the dataset
- `dtype`: pandas dtype string
- `sample`: list of up to 10 representative non-null values
- `all_column_names`: list of all column names in the dataset (for related_columns inference)

## Output
Return a JSON object matching this schema:
```json
{
  "column_name": "...",
  "domain": "...",
  "dtype": "...",
  "sample": [...],
  "placeholders": ["N/A", "ND", "-", 0],
  "related_columns": ["col_a", "col_b"],
  "target_casing": "lowercase | uppercase | as-is"
}
```

## Guidelines
- `placeholders`: values that are syntactically present but semantically missing.
  For numeric columns consider `0`, `-1`, `9999`; for strings consider `"N/A"`, `"ND"`, `"-"`, `"NULL"`.
- `related_columns`: columns that share a semantic relationship (e.g. start/end date, name/code pairs).
- `target_casing`: use `lowercase` for free-text categoricals, `uppercase` for codes/identifiers,
  `as-is` for proper names, dates, or numeric-like fields.
