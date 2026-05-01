# Semantic Describe Prompt (batched first pass)

## Task
Produce a short, factual description for every input column. These descriptions feed an embedding-based retriever that matches each column to the NoiPA canonical registry, so they must capture the column's *meaning*, not its formatting.

## Input
A JSON object with one field:
- `columns`: list of objects, each `{column_name, dtype, sample}` where `sample` is up to 5 representative non-null values.

## Output
Return a JSON object with one field:
- `descriptions`: a list of objects, each `{column_name, description}`, in the same order as the input.

## Rules for `description`
- One sentence, max ~20 words, English.
- State what the column represents, not what it looks like. "Tax year of the income certification" beats "Four-digit year integer between 2020 and 2024".
- When the name is uninformative (e.g. `col_3`, `field_a`), infer meaning from samples and dtype alone.
- When samples and name disagree (e.g. name says "amount" but samples are dates), trust the samples.
- Use NoiPA / Italian Public Administration vocabulary when the data clearly fits (e.g. "fiscal code", "comparto", "contributi previdenziali", "cedolino"). Otherwise stay generic.
- Do NOT prefix with "Column that...", "This column...", or similar boilerplate.
- Do NOT repeat the column name verbatim inside the description.
