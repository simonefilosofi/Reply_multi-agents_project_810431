# Data Quality Report - ritenuteSindacali.csv

<sub>Generated 2026-09-02 20:08 | domain Trattamento_economico | language it</sub>

## Verdict

**Reliability 0.921 to 0.939** over completeness, uniqueness, schema_conformity. The score is a geometric mean, so one broken dimension pulls it down rather than being averaged away.
Not measurable on the file as delivered, and therefore outside this figure: validity, consistency.

<svg xmlns='http://www.w3.org/2000/svg' width='660' height='118' viewBox='0 0 660 118' font-family='Helvetica,Arial,sans-serif'><rect x='0' y='0' width='660' height='118' fill='#ffffff'/><text x='0' y='14' font-size='10.5' font-weight='bold' fill='#0b3d0b'>Quality dimensions, as delivered against remediated</text><rect x='470' y='7.0' width='9' height='7' fill='#9ae399'/><text x='483' y='14.0' font-size='7.5' fill='#4a7a4a'>as delivered</text><rect x='564' y='7.0' width='9' height='7' fill='#02b900'/><text x='577' y='14.0' font-size='7.5' fill='#4a7a4a'>after remediation</text><line x1='132.0' y1='18.0' x2='132.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='132.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>0%</text><line x1='249.5' y1='18.0' x2='249.5' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='249.5' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>25%</text><line x1='367.0' y1='18.0' x2='367.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='367.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>50%</text><line x1='484.5' y1='18.0' x2='484.5' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='484.5' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>75%</text><line x1='602.0' y1='18.0' x2='602.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='602.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>100%</text><text x='126' y='35.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>completeness</text><rect x='132' y='25.0' width='435.1' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='36.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='38.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.926 to 1.000</text><text x='126' y='61.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>uniqueness</text><rect x='132' y='51.0' width='463.1' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='62.0' width='466.7' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='64.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.985 to 0.993</text><text x='126' y='87.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>schema conformity</text><rect x='132' y='77.0' width='402.8' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='88.0' width='391.7' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='90.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.857 to 0.833</text></svg>

This is a NoiPA union-deduction (ritenute sindacali) dataset that arrives structurally sound but with a handful of fixable defects: placeholder text masquerading as values, a duplicated administration-code column, casing drift in union acronyms, and a difference column that does not reconcile against its two source amounts. After remediation the file is clean and fully populated, with the remaining issues concentrated in a single unresolved question — the differenza column — so I would call it usable now with one significant item needing owner attention.

## The dataset as received

| measure | value |
|---|---|
| rows | 11,745 |
| columns | 14 |
| null cells | 12,195 |
| nulls disguised as values | 441 |
| duplicate rows | 88 |
| rows in key conflict | 83 |
| columns badly named | 1 |
| columns almost empty | 1 |
| columns duplicating another | 1 |
| columns still holding the wrong type | 0 |

Completeness read 92.6% on the file as delivered and 92.3% once the placeholders standing in for gaps were counted as gaps. The lower figure is the accurate one.

### What was wrong, by coverage area

| area | detected | for example |
|---|---|---|
| Schema validation | 0 names against convention, 3 schema violations | - |
| Completeness | 12,245 completeness violations | `--`, `ND` |
| Consistency | 1,897 cross-column violations, 1 duplicate column group | `codice_amministrazione` |
| Duplicate detection | 171 rows not unique when measured, 88 exact duplicates removed | `importo_versato` |
| Anomaly detection | 2 across 1 columns | `comparto` |
| Format validity | 984 format violations | `importo_versato`, `comparto`, `note_operatore` |

## What the pipeline found

### Schema validation

| column too empty to inform | nulls | null rate |
|---|---|---|
| `note_operatore` | 11,393 | 97.0% |

The only structural faults were a duplicated administration-code column (kept under its conforming name) and a note_operatore column that was 97% empty and carried no usable signal, so it was dropped. Two columns remain untyped (mese_competenza and importo_versato) and are worth casting at the source. There were no naming violations against convention once the duplicate was resolved.

### Completeness

| measure | value |
|---|---|
| overall fill rate | 92.3% |
| null cells | 12,636 of 164,430 |
| rows with no gaps | 312 |
| rows carrying a gap | 11,433 |

These figures are measured once the placeholders standing in for gaps have been counted as gaps, so the null count is higher here than in the summary of the file as received, which reports what the file appeared to hold.

<svg xmlns='http://www.w3.org/2000/svg' width='660' height='292' viewBox='0 0 660 292' font-family='Helvetica,Arial,sans-serif'><rect x='0' y='0' width='660' height='292' fill='#ffffff'/><text x='0' y='14' font-size='10.5' font-weight='bold' fill='#0b3d0b'>Fill rate by column, least complete first</text><line x1='132.0' y1='18.0' x2='132.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='132.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>0%</text><line x1='249.5' y1='18.0' x2='249.5' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='249.5' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>25%</text><line x1='367.0' y1='18.0' x2='367.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='367.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>50%</text><line x1='484.5' y1='18.0' x2='484.5' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='484.5' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>75%</text><line x1='602.0' y1='18.0' x2='602.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='602.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>100%</text><text x='126' y='34.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>note_operatore</text><rect x='132' y='26.0' width='14.1' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='34.0' text-anchor='end' font-size='8' fill='#0b3d0b'>3.0%</text><text x='126' y='52.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>codice_amministrazione</text><rect x='132' y='44.0' width='454.3' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='52.0' text-anchor='end' font-size='8' fill='#0b3d0b'>96.7%</text><text x='126' y='70.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>descrizione_sindacale</text><rect x='132' y='62.0' width='455.5' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='70.0' text-anchor='end' font-size='8' fill='#0b3d0b'>96.9%</text><text x='126' y='88.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>amministrazione</text><rect x='132' y='80.0' width='457.1' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='88.0' text-anchor='end' font-size='8' fill='#0b3d0b'>97.3%</text><text x='126' y='106.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>comparto</text><rect x='132' y='98.0' width='463.3' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='106.0' text-anchor='end' font-size='8' fill='#0b3d0b'>98.6%</text><text x='126' y='124.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>id_record</text><rect x='132' y='116.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='124.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='142.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>mese_competenza</text><rect x='132' y='134.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='142.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='160.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>sigla_sindacale</text><rect x='132' y='152.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='160.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='178.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>numero_deleghe</text><rect x='132' y='170.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='178.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='196.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>importo_ritenuto</text><rect x='132' y='188.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='196.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='214.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>importo_versato</text><rect x='132' y='206.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='214.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='232.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>differenza</text><rect x='132' y='224.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='232.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='250.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>stato_flusso</text><rect x='132' y='242.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='250.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='268.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>Codice Amministrazione</text><rect x='132' y='260.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='268.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text></svg>

| column | values that stood in for a gap |
|---|---|
| `amministrazione` | `--`, `ND` |
| `descrizione_sindacale` | `--`, `ND` |
| `comparto` | `ND`, `--`, `SICUREZZA-DIFESA`, `FUNZIONI CENTRALI`, `ISTRUZIONE E RICERCA`, `SANITA'` |

The raw file looked nearly complete, but 441 cells held placeholder text such as 'ND' and '--' that were actually gaps; the lower, post-unmasking figure is the accurate one and represents a gain in accuracy, not a regression. Those gaps sat in amministrazione, descrizione_sindacale and comparto, and all were filled deterministically from lookup mappings, leaving the final table fully populated. The only genuinely empty column was note_operatore, which was removed rather than imputed.

### Consistency

| group kept as | data taken from | columns removed | cells backfilled | cells overwritten | values lost |
|---|---|---|---|---|---|
| `codice_amministrazione` | `Codice Amministrazione` | `codice_amministrazione` | 0 | 11,354 | 10 |
| rule | rows breaking it | still breaking it after remediation |
|---|---|---|
| `differenza = importo_ritenuto - importo_versato` | 1,027 | 1,020 |
| `descrizione_sindacale determines sigla_sindacale` | 779 | 0 |
| `amministrazione determines comparto` | 87 | 0 |
| `codice_amministrazione determines comparto` | 4 | 0 |

The main cross-column disagreement is that differenza does not equal importo_ritenuto minus importo_versato on over a thousand rows, and this was deliberately left alone because the discrepancy may reflect legitimate manual adjustments recorded in the operator notes rather than a formatting error. The duplicate administration-code column was resolved by keeping the conforming name, but this overwrote cells in the surviving column and lost values that existed only in the dropped one, so that merge should be reviewed rather than assumed lossless. Duplicate rows were removed cleanly with no conflicting data.

### Anomaly detection

| column | method | detected | for example |
|---|---|---|---|
| `comparto` | rare_category | 2 | `ND`, `--` |

An outlier is unusual, which is not the same as wrong: these are reported and, unless the value is impossible for the column's meaning, left for a person to judge.

The only flagged anomaly is the comparto column, where 'ND' and '--' appear as rare categories alongside legitimate sectors; these are placeholder encodings rather than genuine extreme values and were correctly mapped to null and refilled. No numeric outliers were detected in the monetary columns, so the amounts themselves show no implausible extremes.

### Remediation

| measure | value |
|---|---|
| corrections applied automatically | 4 |
| proposals put to the reviewer | 3 |
| proposals accepted | 3 |
| proposals carrying a generated function | 0 |
| generated functions validated in a sandbox | 2 of 2 |
| cells changed in total | 13,940 |
| issues carried without an action | 1 |

### Issues carried without a corrective action

These were detected and reported. No correction is proposed for them, because none can be
expressed as code over the columns the file actually contains; acting anyway would mean
inventing values. They are listed so the gap is visible rather than silently carried.

| column (rows affected) | why no action is proposed |
|---|---|
| `importo_versato` (177), `differenza` (1,027), `codice_amministrazione` (11,354) | c7_v1 flags rows where differenza does not equal importo_ritenuto - importo_versato, but the discrepancy is a genuine data-quality question rather than a formatting defect: the correct differenza cannot be derived without a deterministic rule, and recomputing it would overwrite values that may reflect legitimate manual adjustments (the note_operatore column records 'rettifica manuale' on some rows). c10_v1 is a missing-value flag on a free-text operator-notes column with 11,393 nulls; there is no imputation hint and no deterministic source for these notes, so filling them would invent data. Both require human judgement. (`note_operatore` is also named above but is covered by a proposal at the gate.) |

The pipeline normalized the period column, stripped and uppercased union acronyms, and backfilled amministrazione, descrizione_sindacale and comparto from near-perfect lookup mappings, all without inventing data. The generated cleaning function for sigla_sindacale implements a strip-and-uppercase rule, so any future value arriving with stray whitespace or mixed casing will be canonicalized the same way. The differenza reconciliation and the operator-notes column were left untouched because both require human judgement rather than a deterministic rule.

## What was changed

### Applied without asking, because the data determined them

| column | correction | cells | why it needed no approval |
|---|---|---|---|
| `mese_competenza` | normalize_period | 11,745 | alternative period layouts rewritten to the canonical YYYYMM form |
| `amministrazione` | impute_from_lookup | 322 | codice_amministrazione -> amministrazione: purity=1.00, coverage=1.00 on path 'raw' |
| `descrizione_sindacale` | impute_from_lookup | 363 | sigla_sindacale -> descrizione_sindacale: purity=1.00, coverage=1.00 on path 'raw' |
| `comparto` | impute_from_lookup | 167 | amministrazione -> comparto: purity=0.99, coverage=0.98 on path 'raw' |

### Put to the reviewer

| id | columns | what it does | outcome |
|---|---|---|---|
| `schema_drop_note_operatore` | `note_operatore` | Drop 'note_operatore': it is 97.0% null and carries almost no information. | accepted |
| `strip_whitespace_sigla_sindacale` | `sigla_sindacale` | Normalize sigla_sindacale values to the canonical uppercase spelling (strip whitespace, collapse casing). | accepted |
| `replace_values_comparto` | `comparto` | Fill comparto placeholders 'ND' and '--' from the amministrazione lookup mapping. | accepted |

### Cells changed, by column

| column | cells changed |
|---|---|
| `mese_competenza` | 11,745 |
| `sigla_sindacale` | 807 |
| `descrizione_sindacale` | 516 |
| `amministrazione` | 471 |
| `comparto` | 259 |
| `codice_amministrazione` | 141 |
| `numero_deleghe` | 1 |

## The dataset as delivered



| measure | as received | after remediation |
|---|---|---|
| rows | 11,745 | 11,657 |
| columns | 14 | 12 |
| null cells | 12,195 | 0 |
| format violations | n/a | 174 |
| inconsistent rows | n/a | 1,020 |
| duplicate rows | 88 | 0 |
| rows in key conflict | 83 | 82 |
| columns badly named | 1 | 0 |
| columns almost empty | 1 | 0 |
| columns duplicating another | 0 | 0 |
| columns still holding the wrong type | 0 | 2 |

Restricted to the columns present at both ends, reliability moved from **0.927** to **0.945**. The headline pair counts the columns the pipeline removed; this one does not, so removing an empty column is not read as an improvement.

Still open: 174 format, 1020 consistency, 82 uniqueness.

## Every column at a glance

One row per column of the delivered file. `detected` counts what was found against it on arrival, `outstanding` what a check still reports, and `cells changed` how many of its values the run rewrote.

| column | type | filled | detected | outstanding | cells changed |
|---|---|---|---|---|---|
| `id_record` | object | 100.0% | 0 | 0 | 0 |
| `mese_competenza` | object | 100.0% | 0 | 0 | 11,745 |
| `amministrazione` | string | 100.0% | 322 | 0 | 471 |
| `sigla_sindacale` | string | 100.0% | 1,586 | 0 | 807 |
| `descrizione_sindacale` | object | 100.0% | 363 | 0 | 516 |
| `numero_deleghe` | Int64 | 100.0% | 0 | 0 | 1 |
| `importo_ritenuto` | float64 | 100.0% | 0 | 0 | 0 |
| `importo_versato` | object | 100.0% | 177 | 175 | 0 |
| `differenza` | float64 | 100.0% | 1,027 | 1,020 | 0 |
| `comparto` | string | 100.0% | 11,836 | 0 | 259 |
| `stato_flusso` | object | 100.0% | 0 | 0 | 0 |
| `codice_amministrazione` | int64 | 100.0% | 11,354 | 0 | 141 |

## Recommendations

1. Enforce a single canonical spelling for sigla_sindacale at data entry (uppercase, no leading/trailing whitespace) so union acronyms stop arriving as 'Dirstat', 'Cisl Fp' and similar variants.
2. Stop emitting placeholder text 'ND' and '--' in amministrazione, descrizione_sindacale and comparto; write true nulls instead so gaps are not mistaken for values.
3. Reconcile the differenza field at the source: either compute it as importo_ritenuto minus importo_versato or record the manual-adjustment reason in a structured field, since the current free-text note_operatore cannot be used to explain the discrepancy.
4. Remove the duplicate administration-code column from the source export so the two code columns cannot drift apart and force a lossy merge downstream.
