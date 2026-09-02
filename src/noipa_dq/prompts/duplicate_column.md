# Duplicate Column Agent Prompt

## Task
Two or more columns in the dataset have identical value sets (same hash).
Choose which column name to retain as the canonical one; the others will be dropped.

## Input
- `duplicate_group`: list of column names that are duplicates
- `domain`: detected dataset domain
- `baseline_columns`: column names present in the baseline for this domain

## Output
Return a JSON object:
- `canonical_name`: MUST be one of the names in `duplicate_group`.
- `rationale`: one short sentence explaining the choice.

## Guidelines
- If any name in `duplicate_group` matches a `baseline_columns` entry, prefer it.
- Otherwise prefer the most descriptive or conventional name; avoid cryptic abbreviations.
