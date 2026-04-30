# Semantic Agent Prompt

## Task
Analyze a single dataset column and return a structured semantic payload.

## Input
- `column_name`: string
- `dataset_domain`: detected domain of the whole dataset
- `dtype`: pandas-inferred dtype string
- `sample`: up to 10 representative non-null values
- `all_column_names`: every column name in the dataset (for `related_columns`)
- `placeholder_candidates`: values literally observed in this column that match a curated
  list of generic disguised-NaN tokens. They were detected programmatically — your job
  is to **filter** them by column meaning, not extend them.

## Output
Return a JSON object with these fields:
- `dtype`: most accurate pandas dtype. If values are clearly numeric or datetimes, return
  `float64` / `int64` / `datetime64[ns]` instead of `object`.
- `column_meaning`: a short phrase (max ~10 words) describing what this column represents
  in context (e.g. "monthly gross salary in euro", "employee fiscal code",
  "contract start date").
- `placeholders`: a SUBSET of `placeholder_candidates`. Keep a candidate only if it is
  implausible as a real value for this column's meaning; drop it if it could legitimately
  occur. Do NOT add values that are not in `placeholder_candidates`.
  Example: for a "monthly salary" column, the candidate `0` is a plausible real value
  (unpaid period) and must be DROPPED; for a "country code" column, `0` is implausible
  and KEPT. For free-text fields, tokens like `"-"`, `"n/a"`, `"tbd"` are virtually
  always placeholders.
- `related_columns`: other column names sharing a semantic relationship
  (e.g. start/end date pairs, name/code pairs).
- `target_casing`: one of `lowercase`, `uppercase`, `as-is`.
  - `lowercase` for free-text categoricals,
  - `uppercase` for codes / identifiers / acronyms,
  - `as-is` for proper names AND ALWAYS for numeric, datetime, or boolean columns.
