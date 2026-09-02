# Data Quality Report - spesa.csv

<sub>Generated 2026-09-02 20:08 | domain Trattamento_economico | language it</sub>

## Verdict

**Reliability 0.756 to 0.993** over completeness, uniqueness, schema_conformity. The score is a geometric mean, so one broken dimension pulls it down rather than being averaged away.
Not measurable on the file as delivered, and therefore outside this figure: validity, consistency.

<svg xmlns='http://www.w3.org/2000/svg' width='660' height='118' viewBox='0 0 660 118' font-family='Helvetica,Arial,sans-serif'><rect x='0' y='0' width='660' height='118' fill='#ffffff'/><text x='0' y='14' font-size='10.5' font-weight='bold' fill='#0b3d0b'>Quality dimensions, as delivered against remediated</text><rect x='470' y='7.0' width='9' height='7' fill='#9ae399'/><text x='483' y='14.0' font-size='7.5' fill='#4a7a4a'>as delivered</text><rect x='564' y='7.0' width='9' height='7' fill='#02b900'/><text x='577' y='14.0' font-size='7.5' fill='#4a7a4a'>after remediation</text><line x1='132.0' y1='18.0' x2='132.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='132.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>0%</text><line x1='249.5' y1='18.0' x2='249.5' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='249.5' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>25%</text><line x1='367.0' y1='18.0' x2='367.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='367.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>50%</text><line x1='484.5' y1='18.0' x2='484.5' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='484.5' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>75%</text><line x1='602.0' y1='18.0' x2='602.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='602.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>100%</text><text x='126' y='35.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>completeness</text><rect x='132' y='25.0' width='411.3' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='36.0' width='460.6' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='38.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.875 to 0.980</text><text x='126' y='61.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>uniqueness</text><rect x='132' y='51.0' width='464.4' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='62.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='64.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.988 to 1.000</text><text x='126' y='87.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>schema conformity</text><rect x='132' y='77.0' width='235.0' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='88.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='90.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.500 to 1.000</text></svg>

This is a NoiPA payroll expenditure dataset covering tax and deduction amounts across Italian public administrations. After remediation it is in good, usable shape: structural defects are gone, consistency and uniqueness are fully resolved, and the only remaining weakness is a genuine gap in the area_geografica field. The dataset is clean enough for analysis, with the geographic coverage gap being the one issue that still needs attention at the source.

## The dataset as received

| measure | value |
|---|---|
| rows | 7,543 |
| columns | 18 |
| null cells | 16,939 |
| nulls disguised as values | 988 |
| duplicate rows | 40 |
| rows in key conflict | 50 |
| columns badly named | 7 |
| columns almost empty | 2 |
| columns duplicating another | 4 |
| columns still holding the wrong type | 0 |

Completeness read 87.5% on the file as delivered and 86.8% once the placeholders standing in for gaps were counted as gaps. The lower figure is the accurate one.

### What was wrong, by coverage area

| area | detected | for example |
|---|---|---|
| Schema validation | 2 names against convention, 5 schema violations | `_id`, `aggregation-time` |
| Completeness | 17,337 completeness violations | `n.d.`, `?`, `//` |
| Consistency | 517 cross-column violations, 4 duplicate column groups | `ente`, `tipo_imposta`, `cod_imposta` |
| Duplicate detection | 87 rows not unique when measured, 65 exact duplicates removed | - |
| Anomaly detection | 1354 across 2 columns | `imposta`, `spesa` |
| Format validity | 513 format violations | `descrizione`, `note`, `fonte_dato` |

## What the pipeline found

### Schema validation

| column | suggested name |
|---|---|
| `_id` | `id` |
| `aggregation-time` | `aggregation_time` |

| column too empty to inform | nulls | null rate |
|---|---|---|
| `note` | 7,393 | 98.0% |
| `fonte_dato` | 7,468 | 99.0% |

The raw file carried seven badly named columns, two near-empty columns (note and fonte_dato, at roughly 98% and 99% null), and a redundant tax-code column, all of which have now been renamed, dropped, or consolidated. The duplicate-column groups were the most consequential: tipo_imposta and spesa each existed twice under different names, and the surviving versions disagreed with the dropped ones on hundreds of cells. These naming and duplication problems are worth fixing at the source so each field is exported once, under one canonical name.

### Completeness

| measure | value |
|---|---|
| overall fill rate | 86.8% |
| null cells | 17,927 of 135,774 |
| rows with no gaps | 1 |
| rows carrying a gap | 7,542 |

These figures are measured once the placeholders standing in for gaps have been counted as gaps, so the null count is higher here than in the summary of the file as received, which reports what the file appeared to hold.

<svg xmlns='http://www.w3.org/2000/svg' width='660' height='292' viewBox='0 0 660 292' font-family='Helvetica,Arial,sans-serif'><rect x='0' y='0' width='660' height='292' fill='#ffffff'/><text x='0' y='14' font-size='10.5' font-weight='bold' fill='#0b3d0b'>Fill rate by column, least complete first</text><line x1='132.0' y1='18.0' x2='132.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='132.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>0%</text><line x1='249.5' y1='18.0' x2='249.5' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='249.5' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>25%</text><line x1='367.0' y1='18.0' x2='367.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='367.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>50%</text><line x1='484.5' y1='18.0' x2='484.5' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='484.5' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>75%</text><line x1='602.0' y1='18.0' x2='602.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='602.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>100%</text><text x='126' y='34.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>fonte_dato</text><rect x='132' y='26.0' width='4.7' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='34.0' text-anchor='end' font-size='8' fill='#0b3d0b'>1.0%</text><text x='126' y='52.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>note</text><rect x='132' y='44.0' width='9.4' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='52.0' text-anchor='end' font-size='8' fill='#0b3d0b'>2.0%</text><text x='126' y='70.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>area_geografica</text><rect x='132' y='62.0' width='371.4' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='70.0' text-anchor='end' font-size='8' fill='#0b3d0b'>79.0%</text><text x='126' y='88.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>descrizione</text><rect x='132' y='80.0' width='441.6' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='88.0' text-anchor='end' font-size='8' fill='#0b3d0b'>94.0%</text><text x='126' y='106.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>imposta</text><rect x='132' y='98.0' width='446.4' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='106.0' text-anchor='end' font-size='8' fill='#0b3d0b'>95.0%</text><text x='126' y='124.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>ente</text><rect x='132' y='116.0' width='451.2' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='124.0' text-anchor='end' font-size='8' fill='#0b3d0b'>96.0%</text><text x='126' y='142.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>cod_imposta</text><rect x='132' y='134.0' width='456.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='142.0' text-anchor='end' font-size='8' fill='#0b3d0b'>97.0%</text><text x='126' y='160.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>spesa</text><rect x='132' y='152.0' width='466.2' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='160.0' text-anchor='end' font-size='8' fill='#0b3d0b'>99.2%</text><text x='126' y='178.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>SPESA TOTALE</text><rect x='132' y='170.0' width='466.3' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='178.0' text-anchor='end' font-size='8' fill='#0b3d0b'>99.2%</text><text x='126' y='196.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>tipo_imposta</text><rect x='132' y='188.0' width='469.9' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='196.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='214.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>_id</text><rect x='132' y='206.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='214.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='232.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>rata</text><rect x='132' y='224.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='232.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='250.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>cod_tipoimposta</text><rect x='132' y='242.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='250.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='268.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>aggregation-time</text><rect x='132' y='260.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='268.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text></svg>

| column | values that stood in for a gap |
|---|---|
| `descrizione` | `n.d.`, `?`, `//`, `ND`, ` `, `-`, `unknown`, `N/A ` |
| `imposta` | `-`, `//`, `TBD`, ` `, `unknown`, `DA VERIFICARE`, `?`, `ND` |
| `spesa` | `N.D.` |

The apparent completeness of the raw file was flattered by placeholder text such as n.d., TBD, and DA VERIFICARE that counted as values until unmasked; the lower figure is the accurate one, and the drop is a gain in accuracy rather than a regression. After remediation the only meaningful gap is area_geografica, which is missing for about one row in five and cannot be filled without inventing data. The descrizione and imposta gaps were closed deterministically from ente and cod_imposta lookups, leaving only a handful of unresolved entity names.

### Consistency

| group kept as | data taken from | columns removed | cells backfilled | cells overwritten | values lost |
|---|---|---|---|---|---|
| `ente` | `ente%code` | `ente` | 0 | 0 | 0 |
| `tipo_imposta` | `Tipo Imposta` | `tipo_imposta` | 0 | 383 | 5 |
| `cod_imposta` | `2cod_imposta` | `cod_imposta`, `cod imposta ext` | 0 | 0 | 0 |
| `spesa` | `SPESA TOTALE` | `spesa` | 0 | 37 | 10 |
| rule | rows breaking it | still breaking it after remediation |
|---|---|---|
| `aggregation-time determines rata` | 510 | 0 |
| `cod_imposta determines imposta` | 4 | 0 |
| `imposta determines tipo_imposta` | 1 | 0 |
| `imposta determines cod_tipoimposta` | 1 | 0 |
| `imposta determines cod_imposta` | 1 | 0 |

The file as delivered held 40 exact duplicate rows, and 65 were removed. The difference is not a discrepancy: collapsing the duplicate columns left further rows identical to one another that had differed only in the columns that were dropped.

Cross-column rules were almost entirely violated by the rata field, where 510 rows had an installment period inconsistent with the aggregation timestamp; these were corrected from the dependency. Duplicate-column resolution did overwrite cells and lose values: the surviving tipo_imposta column disagreed with the dropped one on 383 cells, and the surviving spesa column overwrote 37 cells while discarding values that existed only in the dropped column, including a clearly erroneous -45000.0 and a suspicious 1234567890.0. Sixty-five exact duplicate rows were removed with no conflicting data among them.

### Anomaly detection

| column | method | detected | for example |
|---|---|---|---|
| `imposta` | rare_category | 2 | `imposta x`, `Altro` |
| `spesa` | iqr | 1,352 | `2110811.34`, `43365008.73`, `2192935.66` |

An outlier is unusual, which is not the same as wrong: these are reported and, unless the value is impossible for the column's meaning, left for a person to judge.

The spesa outliers flagged by the IQR method are mostly plausible high-value payroll transactions rather than errors, since expenditure aggregates legitimately span a wide range; however the extreme values near 43 million and the placeholder-like 1234567890.0 deserve a manual look as possible data-entry inflation. In imposta, the rare categories "imposta x" and "Altro" are free-text or placeholder entries that were correctly mapped back to their standard tax labels via the cod_imposta lookup.

### Remediation

| measure | value |
|---|---|
| corrections applied automatically | 5 |
| proposals put to the reviewer | 6 |
| proposals accepted | 6 |
| proposals carrying a generated function | 0 |
| generated functions validated in a sandbox | 0 |
| cells changed in total | 5,659 |
| issues carried without an action | 1 |

### Issues carried without a corrective action

These were detected and reported. No correction is proposed for them, because none can be
expressed as code over the columns the file actually contains; acting anyway would mean
inventing values. They are listed so the gap is visible rather than silently carried.

| column (rows affected) | why no action is proposed |
|---|---|
| `cod_tipoimposta` (1), `area_geografica` (1,582), `tipo_imposta` (384), `spesa` (59), `cod_imposta` (1) | The missing values in area_geografica (1582), note (7393), fonte_dato (7468), and spesa (59) cannot be safely filled: none of these columns has an imputation hint, and filling them would require inventing data or applying a statistic without a deterministic rule. area_geografica, note, and fonte_dato have no predictor columns in the group, and spesa is a monetary amount that must not be imputed without an explicit user-provided rule. These require human judgement. (`aggregation-time`, `note`, `fonte_dato` are also named above but are covered by a proposal at the gate.) |

The pipeline repaired installment-period formatting, rounded floating-point noise in spesa, and imputed descrizione and imposta from high-purity lookups, while leaving area_geografica and the residual spesa gaps untouched because no deterministic rule exists to fill them. No cleaning function was generated for future use, so the repairs are one-off corrections rather than reusable rules. The two near-empty columns were dropped as a schema decision, which is appropriate given they carried almost no information.

## What was changed

### Applied without asking, because the data determined them

| column | correction | cells | why it needed no approval |
|---|---|---|---|
| `rata` | normalize_period | 414 | alternative period layouts rewritten to the canonical YYYYMM form |
| `spesa` | round_decimals | 2,878 | the column is recorded at 2 decimals; the extra digits are floating-point noise and rounding leaves the totals unchanged |
| `rata` | complete_period_from_dependency | 96 | values naming only a year were completed from a column that determines rata exactly |
| `descrizione` | impute_from_lookup | 448 | ente -> descrizione: purity=0.99, coverage=0.98 on path 'raw' |
| `imposta` | impute_from_lookup | 379 | cod_imposta -> imposta: purity=1.00, coverage=1.00 on path 'raw' |

### Put to the reviewer

| id | columns | what it does | outcome |
|---|---|---|---|
| `schema_drop_note` | `note` | Drop 'note': it is 98.0% null and carries almost no information. | accepted |
| `schema_drop_fonte_dato` | `fonte_dato` | Drop 'fonte_dato': it is 99.0% null and carries almost no information. | accepted |
| `schema_rename__id` | `_id` | Rename '_id' to 'id' to match the naming convention. | accepted |
| `schema_rename_aggregation-time` | `aggregation-time` | Rename 'aggregation-time' to 'aggregation_time' to match the naming convention. | accepted |
| `impute_from_lookup_descrizione` | `descrizione` | Fill missing descrizione values from the ente-to-descrizione mapping derived from non-missing rows of the dataframe. | accepted |
| `replace_values_imposta` | `imposta` | Correct the placeholder 'imposta x' and the stray 'Altro' value in imposta using the cod_imposta lookup. | accepted |

### Cells changed, by column

| column | cells changed |
|---|---|
| `spesa` | 2,979 |
| `descrizione` | 758 |
| `imposta` | 625 |
| `rata` | 510 |
| `tipo_imposta` | 387 |
| `ente` | 185 |
| `cod_imposta` | 154 |
| `SPESA TOTALE` | 60 |
| `aggregation-time` | 1 |

## The dataset as delivered



| measure | as received | after remediation |
|---|---|---|
| rows | 7,543 | 7,478 |
| columns | 18 | 11 |
| null cells | 16,939 | 1,633 |
| format violations | n/a | 0 |
| inconsistent rows | n/a | 0 |
| duplicate rows | 40 | 0 |
| rows in key conflict | 50 | 0 |
| columns badly named | 7 | 0 |
| columns almost empty | 2 | 0 |
| columns duplicating another | 1 | 0 |
| columns still holding the wrong type | 0 | 0 |

Restricted to the columns present at both ends, reliability moved from **0.938** to **0.996**. The headline pair counts the columns the pipeline removed; this one does not, so removing an empty column is not read as an improvement.

Still open: 1633 completeness.

## Every column at a glance

One row per column of the delivered file. `detected` counts what was found against it on arrival, `outstanding` what a check still reports, and `cells changed` how many of its values the run rewrote.

| column | type | filled | detected | outstanding | cells changed |
|---|---|---|---|---|---|
| `id`<br><sub>from _id</sub> | object | 100.0% | 0 | 0 | 0 |
| `rata` | object | 100.0% | 1,020 | 0 | 510 |
| `descrizione` | string | 99.9% | 456 | 8 | 758 |
| `cod_tipoimposta` | int64 | 100.0% | 1 | 0 | 0 |
| `imposta` | object | 100.0% | 386 | 0 | 625 |
| `aggregation_time`<br><sub>from aggregation-time</sub> | datetime64[ns] | 100.0% | 0 | 0 | 0 |
| `area_geografica` | object | 79.0% | 1,582 | 1,567 | 0 |
| `tipo_imposta` | object | 100.0% | 384 | 0 | 387 |
| `spesa` | float64 | 99.2% | 59 | 58 | 2,979 |
| `cod_imposta` | int64 | 100.0% | 1 | 0 | 154 |
| `ente` | int64 | 100.0% | 0 | 0 | 185 |

## Recommendations

1. Populate area_geografica at the source: require the macro-area (Nord, Centro, Sud, Isole) to be derived from the entity's registered address at data-entry time, since it is currently missing for roughly one in five rows and cannot be safely imputed downstream.
2. Enforce a single canonical export for each field: tipo_imposta and spesa are each emitted twice under different names with conflicting values, so the source system should write one column per concept using the agreed naming convention.
3. Validate spesa against a plausible range at entry, rejecting negative amounts and flagging values above a domain-specific ceiling, since the data contained a -45000.0 and a 1234567890.0 placeholder.
4. Replace free-text tax labels in imposta with the cod_imposta-driven enum so values like 'imposta x' and 'Altro' cannot be entered, keeping the label fully determined by the code.
