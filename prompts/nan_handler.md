# NaN Handler Agent Prompt

## Task
Given a column and its placeholder list from the payload, confirm whether any additional
values not already in the list should also be treated as disguised NaNs.

## Input
- `column_name`: string
- `dtype`: column dtype
- `known_placeholders`: list already identified by the Semantic Agent
- `remaining_suspicious`: list of values found in the column that look unusual but are not in `known_placeholders`

## Output
Return a JSON object:
```json
{
  "additional_placeholders": [...],
  "rationale": "<one sentence>"
}
```

## Guidelines
- Only flag values that are clearly implausible as real data for this column's dtype and domain.
- Do not flag low-frequency legitimate values.
