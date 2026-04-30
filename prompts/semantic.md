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
- `related_columns`: other columns from `all_column_names` that share a semantic relationship with this one.
  Be thorough — these links feed the downstream consistency agent. Include every relevant counterpart you
  can identify, not just the most obvious one. Look for:
  - **Paired bounds**: start/end, min/max, from/to (e.g. `eta_min`/`eta_max`, `data_inizio`/`data_fine`,
    `distance_min_KM`/`distance_max_KM`, `fascia_reddito_min`/`fascia_reddito_max`).
  - **Code/label pairs**: a code column and its descriptive counterpart (e.g. `cod_ente`/`ente`,
    `cod_imposta`/`imposta`, `provincia_code`/`provincia_della_sede`).
  - **Geographic hierarchy**: columns at different administrative levels of the same place
    (e.g. `comune`/`provincia`/`regione`/`area_geografica`).
  - **Composite identity**: columns that together identify the same entity or event (e.g. demographics
    bundle `sesso`/`eta_min`/`eta_max`; a payslip's `imponibile`/`importo_IRPEF`/`numero_cedolini`).
  - **Aggregation pairs**: a value column and its count/denominator
    (e.g. `importo_lavoratore` paired with `numero_cedolini`; `numero` paired with the dimensions it counts).
  - **Worker/employer mirrors**: split contributions referring to the same scheme
    (e.g. `importo_lavoratore`/`importo_datore`).
  Return an empty list only when no such relationship exists. Symmetry is expected — if column A lists B, B
  should list A.
- `target_casing`: one of `lowercase`, `uppercase`, `as-is`.
  - `lowercase` for free-text categoricals, `uppercase` for codes / identifiers / acronyms,
  - `as-is` for proper names AND ALWAYS for numeric, datetime, or boolean columns.
- `canonical_match`: the `canonical_id` from `canonical_suggestion` or from an entry in `domain_catalog`
  that this input column most likely represents — OR `null` if the column is novel and has no canonical
  equivalent in the catalog.

## Rules for `canonical_match`
A `canonical_match` is a binding contract — downstream agents will enforce the matched spec's dtype,
format, case_convention, and is_nullable on this column. Be conservative: prefer `null` when in doubt.

- Confirm a `canonical_suggestion` ONLY when ALL of the following hold:
  1. The input column's `column_meaning` is the same concept as the canonical id (not merely related).
  2. The samples are consistent with the suggestion's `dtype` (a numeric column cannot match a string spec).
  3. The samples are consistent with the suggestion's `format` — for an `enum`, all (or nearly all) sample
     values appear in the enum value set; for a `regex`, sample values plausibly match the pattern shape;
     for a `range`, numeric samples fall inside the bounds (range floors like `numero ≥ 6` may be violated
     by disguised-NaN candidates such as `0`, which is fine — the violation is what flags them).
  4. The samples are consistent with the suggestion's `case_convention` (or could be after normalization).
  If ANY check fails, set `canonical_match` to `null` and, when possible, pick a different canonical id
  from `domain_catalog` that satisfies all four checks.
- Two columns describing different facets of the same conceptual entity must NOT both confirm the same
  `canonical_match`. Examples:
  - A code column (`cod_ente` with values like `MEF`, `INPS`) and a label column (`descrizione` /
    `ente_nome` with values like `MINISTERO DELL'ECONOMIA E DELLE FINANZE`) describe the same entity but
    are different columns. At most one of them — the one whose samples actually fit the canonical spec —
    may confirm the canonical match. The other must return `null` for `canonical_match` and instead list
    its counterpart in `related_columns`.
  - Paired bounds (`eta_min`/`eta_max`, `data_inizio`/`data_fine`) match different canonical ids — never
    the same one.
- Use `domain_catalog` (when provided) to explore alternative canonical matches before declaring novel.
  Match by *meaning*, not by exact string — input column names may use synonyms, different casing, or
  different language.
- A `null` `canonical_match` is the correct answer when no entry in the catalog matches the input column's
  meaning, or when the column is conceptually adjacent to a canonical entry but doesn't satisfy all four
  consistency checks above. Never invent a canonical id.
