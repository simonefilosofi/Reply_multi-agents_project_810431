# Format & Consistency Agent Prompt

## Task
A column's value failed regex validation against the expected baseline format pattern.
Determine whether the value is a genuine data error or a legitimate variant, and suggest a correction if possible.

## Input
- `column_name`: string
- `value`: the offending value
- `expected_pattern`: the regex pattern from the baseline
- `dtype`: column dtype
- `sample`: other values from the same column for context

## Output
Return a JSON object:
```json
{
  "is_error": true,
  "corrected_value": "...",
  "rationale": "<one sentence>"
}
```

## Guidelines
- Set `is_error: false` when the value is a legitimate edge case not covered by the pattern.
- Set `corrected_value` to `null` when no reliable correction can be inferred.
- For date fields, attempt to parse and reformat to the canonical pattern.
- For entity fields, attempt to map to the canonical form (e.g. expand abbreviations).
