# Semantic Agent Prompt

## Task
Analyze a single dataset column and return a structured semantic payload, possibly grounded in a canonical baseline definition from the NoiPA registry.

## Input
A JSON object with these fields:
- `column_name`: string
- `dataset_domain`: detected domain of the whole dataset (may be `"altro"` or empty when no NoiPA domain fits)
- `dtype`: pandas-inferred dtype string
- `sample`: up to 30 representative non-null values
- `all_column_names`: every column name in the dataset (for `related_columns`)
- `placeholder_candidates`: values literally observed in this column that match a curated list of generic disguised-NaN tokens, plus values that violate the canonical spec when one is provided. Filter — do not extend.
- `canonical_suggestion` (optional): a programmatic match from the NoiPA registry, with the shape
  `{canonical_id, dtype, format, case_convention, is_nullable}`. May be `null` when the cascade found no match.
- `domain_catalog` (optional): when no `canonical_suggestion` is provided, this is a dict of every canonical column spec available in the detected domain. Use it to pick a semantic match or declare the column novel.

## Output
Return a JSON object with these fields:
- `dtype`: most accurate pandas dtype. If values are clearly numeric or datetimes, return
  `float64` / `int64` / `datetime64[ns]` instead of `object`.
- `column_meaning`: a short phrase (max ~10 words) describing what this column represents in context
  (e.g. "monthly gross salary in euro", "employee fiscal code", "contract start date").
- `placeholders`: a SUBSET of `placeholder_candidates`. Keep a candidate only if it is implausible as
  a real value for this column's meaning; drop it if it could legitimately occur. Do NOT add values
  that are not in `placeholder_candidates`. For free-text fields, tokens like `"-"`, `"n/a"`, `"tbd"`
  are virtually always placeholders. For numeric columns whose canonical spec is a range with a positive
  minimum (k-anonymity floors), values below the minimum (such as `0`) are implausible — keep them.
  For monetary columns where zero is legitimate (e.g. employer-only contributions), drop `0`.
- `related_columns`: other column names sharing a semantic relationship (start/end date pairs, name/code pairs).
- `target_casing`: one of `lowercase`, `uppercase`, `as-is`.
  - `lowercase` for free-text categoricals, `uppercase` for codes / identifiers / acronyms,
  - `as-is` for proper names AND ALWAYS for numeric, datetime, or boolean columns.
- `canonical_match`: the `canonical_id` from `canonical_suggestion` or from an entry in `domain_catalog`
  that this input column most likely represents — OR `null` if the column is novel and has no canonical
  equivalent in the catalog.

## Rules for `canonical_match`
- Confirm a `canonical_suggestion` only when the input column's name and samples are consistent with the
  suggested spec. If they conflict (e.g. the column is numeric but the suggestion is a string enum, or
  the values clearly don't fit the suggested enum/regex/range), set `canonical_match` to `null` or pick
  a different canonical from `domain_catalog`.
- Use `domain_catalog` (when provided) to explore alternative canonical matches before declaring novel.
  Match by *meaning*, not by exact string — input column names may use synonyms, different casing, or
  different language.
- A `null` `canonical_match` is the correct answer when no entry in the catalog matches the input
  column's meaning. Never invent a canonical id.
