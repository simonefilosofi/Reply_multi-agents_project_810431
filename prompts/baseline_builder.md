# Baseline Builder Prompt

## Task
Given a dataset from the Italian Public Administration portal, assign it to one of the following thematic domains:

- `personale` — HR, payroll, headcount, activations/terminations
- `bilancio` — budget, expenditure, financial accounts
- `trasparenza` — transparency, public procurement, tenders
- `territorio` — geography, land use, municipal boundaries
- `sanita` — healthcare, hospitals, medical services
- `istruzione` — education, schools, universities
- `altro` — anything that does not fit the above

## Input
Dataset column names and a sample of values (first 5 rows).

## Output
Return a JSON object:
```json
{
  "domain": "<one of the domains above>",
  "rationale": "<one sentence>"
}
```
