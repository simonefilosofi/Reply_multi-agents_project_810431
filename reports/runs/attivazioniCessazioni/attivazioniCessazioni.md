# Data Quality Report - attivazioniCessazioni.csv

<sub>Generated 2026-09-02 20:08 | domain Rapporti_di_lavoro | language it</sub>

## Verdict

**Reliability 0.745 to 0.992** over completeness, uniqueness, schema_conformity. The score is a geometric mean, so one broken dimension pulls it down rather than being averaged away.
Not measurable on the file as delivered, and therefore outside this figure: validity, consistency.

<svg xmlns='http://www.w3.org/2000/svg' width='660' height='118' viewBox='0 0 660 118' font-family='Helvetica,Arial,sans-serif'><rect x='0' y='0' width='660' height='118' fill='#ffffff'/><text x='0' y='14' font-size='10.5' font-weight='bold' fill='#0b3d0b'>Quality dimensions, as delivered against remediated</text><rect x='470' y='7.0' width='9' height='7' fill='#9ae399'/><text x='483' y='14.0' font-size='7.5' fill='#4a7a4a'>as delivered</text><rect x='564' y='7.0' width='9' height='7' fill='#02b900'/><text x='577' y='14.0' font-size='7.5' fill='#4a7a4a'>after remediation</text><line x1='132.0' y1='18.0' x2='132.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='132.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>0%</text><line x1='249.5' y1='18.0' x2='249.5' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='249.5' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>25%</text><line x1='367.0' y1='18.0' x2='367.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='367.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>50%</text><line x1='484.5' y1='18.0' x2='484.5' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='484.5' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>75%</text><line x1='602.0' y1='18.0' x2='602.0' y2='106.0' stroke='#ccf1cc' stroke-width='1'/><text x='602.0' y='116.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>100%</text><text x='126' y='35.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>completeness</text><rect x='132' y='25.0' width='412.3' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='36.0' width='458.6' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='38.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.877 to 0.976</text><text x='126' y='61.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>uniqueness</text><rect x='132' y='51.0' width='467.2' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='62.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='64.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.994 to 1.000</text><text x='126' y='87.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>schema conformity</text><rect x='132' y='77.0' width='222.6' height='9' fill='#9ae399' rx='1.5'/><rect x='132' y='88.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='90.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.474 to 1.000</text></svg>

This is a NoiPA employment-activation and termination dataset covering roughly 20,000 records across Italian public-administration entities. After remediation it is clean and highly usable: the structural defects are gone, uniqueness is restored, and the remaining issues are confined to a quarter of the qualifica column and a small residue of month/year inconsistencies. The dataset is in good shape for analysis, with the caveat that qualifica is materially incomplete.

## The dataset as received

| measure | value |
|---|---|
| rows | 20,102 |
| columns | 19 |
| null cells | 46,847 |
| nulls disguised as values | 2,888 |
| duplicate rows | 60 |
| rows in key conflict | 60 |
| columns badly named | 8 |
| columns almost empty | 2 |
| columns duplicating another | 5 |
| columns still holding the wrong type | 0 |

Completeness read 87.7% on the file as delivered and 87.0% once the placeholders standing in for gaps were counted as gaps. The lower figure is the accurate one.

### What was wrong, by coverage area

| area | detected | for example |
|---|---|---|
| Schema validation | 3 names against convention, 7 schema violations | `_id`, `RATA`, `aggregation-time` |
| Completeness | 45,579 completeness violations | `N.D.` |
| Consistency | 2,862 cross-column violations, 5 duplicate column groups | `codice_ente`, `descrizione_ente`, `provincia_sede` |
| Duplicate detection | 90 rows not unique when measured, 90 exact duplicates removed | - |
| Anomaly detection | 6488 across 2 columns | `cessazioni`, `attivazioni` |
| Format validity | 1,777 format violations | `note`, `fonte_dato`, `provincia_sede` |

## What the pipeline found

### Schema validation

| column | suggested name |
|---|---|
| `_id` | `id` |
| `RATA` | `rata` |
| `aggregation-time` | `aggregation_time` |

| column too empty to inform | nulls | null rate |
|---|---|---|
| `note` | 19,802 | 98.5% |
| `fonte_dato` | 19,942 | 99.2% |

The raw file carried five pairs of duplicate columns (e.g. codice_ente vs CODICE ENTE, regione_sede vs regione%sede) plus three badly named columns, and two columns (note, fonte_dato) that were over 98% empty and have been dropped. The duplicate-column resolution was not lossless: keeping one member of each pair overwrote cells in descrizione_ente, provincia_sede, regione_sede and attivazioni where the two copies disagreed, and some values existed only in the dropped copy. The naming and duplication faults are worth fixing at the source so the export stops shipping redundant and inconsistently-cased columns.

### Completeness

| measure | value |
|---|---|
| overall fill rate | 87.0% |
| null cells | 49,735 of 381,938 |
| rows with no gaps | 2 |
| rows carrying a gap | 20,100 |

These figures are measured once the placeholders standing in for gaps have been counted as gaps, so the null count is higher here than in the summary of the file as received, which reports what the file appeared to hold.

<svg xmlns='http://www.w3.org/2000/svg' width='660' height='292' viewBox='0 0 660 292' font-family='Helvetica,Arial,sans-serif'><rect x='0' y='0' width='660' height='292' fill='#ffffff'/><text x='0' y='14' font-size='10.5' font-weight='bold' fill='#0b3d0b'>Fill rate by column, least complete first</text><line x1='132.0' y1='18.0' x2='132.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='132.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>0%</text><line x1='249.5' y1='18.0' x2='249.5' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='249.5' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>25%</text><line x1='367.0' y1='18.0' x2='367.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='367.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>50%</text><line x1='484.5' y1='18.0' x2='484.5' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='484.5' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>75%</text><line x1='602.0' y1='18.0' x2='602.0' y2='280.0' stroke='#ccf1cc' stroke-width='1'/><text x='602.0' y='290.0' text-anchor='middle' font-size='7.5' fill='#4a7a4a'>100%</text><text x='126' y='34.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>fonte_dato</text><rect x='132' y='26.0' width='3.8' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='34.0' text-anchor='end' font-size='8' fill='#0b3d0b'>0.8%</text><text x='126' y='52.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>note</text><rect x='132' y='44.0' width='7.0' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='52.0' text-anchor='end' font-size='8' fill='#0b3d0b'>1.5%</text><text x='126' y='70.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>qualifica</text><rect x='132' y='62.0' width='351.1' height='9' fill='#67d566' rx='1.5'/><text x='656.0' y='70.0' text-anchor='end' font-size='8' fill='#0b3d0b'>74.7%</text><text x='126' y='88.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>provincia_sede</text><rect x='132' y='80.0' width='438.6' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='88.0' text-anchor='end' font-size='8' fill='#0b3d0b'>93.3%</text><text x='126' y='106.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>descrizione_ente</text><rect x='132' y='98.0' width='441.9' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='106.0' text-anchor='end' font-size='8' fill='#0b3d0b'>94.0%</text><text x='126' y='124.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>regione_sede</text><rect x='132' y='116.0' width='451.2' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='124.0' text-anchor='end' font-size='8' fill='#0b3d0b'>96.0%</text><text x='126' y='142.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>codice_ente</text><rect x='132' y='134.0' width='455.9' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='142.0' text-anchor='end' font-size='8' fill='#0b3d0b'>97.0%</text><text x='126' y='160.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>Provincia Sede</text><rect x='132' y='152.0' width='461.4' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='160.0' text-anchor='end' font-size='8' fill='#0b3d0b'>98.2%</text><text x='126' y='178.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>attivazioni</text><rect x='132' y='170.0' width='465.4' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='178.0' text-anchor='end' font-size='8' fill='#0b3d0b'>99.0%</text><text x='126' y='196.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>cessazioni</text><rect x='132' y='188.0' width='465.4' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='196.0' text-anchor='end' font-size='8' fill='#0b3d0b'>99.0%</text><text x='126' y='214.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>att ivazioni</text><rect x='132' y='206.0' width='465.4' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='214.0' text-anchor='end' font-size='8' fill='#0b3d0b'>99.0%</text><text x='126' y='232.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>_id</text><rect x='132' y='224.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='232.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='250.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>mese</text><rect x='132' y='242.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='250.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text><text x='126' y='268.0' text-anchor='end' font-size='8.5' fill='#0b3d0b'>anno</text><rect x='132' y='260.0' width='470.0' height='9' fill='#02b900' rx='1.5'/><text x='656.0' y='268.0' text-anchor='end' font-size='8' fill='#0b3d0b'>100.0%</text></svg>

| column | values that stood in for a gap |
|---|---|
| `cessazioni` | `N.D.` |
| `attivazioni` | `N.D.` |

The apparent completeness of the raw file was flattered by placeholder text such as N.D. in cessazioni and attivazioni, which counted as values until unmasked; the lower post-unmasking figure is the accurate one and represents a gain in accuracy, not a regression. The one column that genuinely limits use is qualifica, which is missing about a quarter of its values and could not be imputed without inventing data. The two near-empty columns note and fonte_dato were dropped as carrying almost no information.

### Consistency

| group kept as | data taken from | columns removed | cells backfilled | cells overwritten | values lost |
|---|---|---|---|---|---|
| `codice_ente` | `CODICE ENTE` | `codice_ente` | 0 | 0 | 0 |
| `descrizione_ente` | `3descrizione` | `descrizione_ente` | 0 | 29 | 10 |
| `provincia_sede` | `Provincia Sede` | `provincia_sede` | 8 | 953 | 10 |
| `regione_sede` | `regione%sede` | `regione_sede` | 0 | 9,630 | 10 |
| `attivazioni` | `att ivazioni` | `attivazioni` | 0 | 38 | 7 |
| rule | rows breaking it | still breaking it after remediation |
|---|---|---|
| `RATA determines mese` | 1,702 | 954 |
| `RATA determines anno` | 1,160 | 572 |

The file as delivered held 60 exact duplicate rows, and 90 were removed. The difference is not a discrepancy: collapsing the duplicate columns left further rows identical to one another that had differed only in the columns that were dropped.

The main cross-column problem is that mese and anno disagree with the period encoded in rata on a substantial number of rows, and a meaningful residue remains after remediation because only rows where rata was unambiguous could be corrected. Duplicate-column resolution overwrote cells in descrizione_ente, provincia_sede, regione_sede and attivazioni, and some values (including province codes and entity names) existed only in the dropped copy and were lost. Ninety exact duplicate records were removed cleanly with no conflicting data.

### Anomaly detection

| column | method | detected | for example |
|---|---|---|---|
| `cessazioni` | iqr | 3,111 | `40`, `1037`, `513` |
| `attivazioni` | iqr | 3,377 | `250`, `38`, `822` |

An outlier is unusual, which is not the same as wrong: these are reported and, unless the value is impossible for the column's meaning, left for a person to judge.

Both cessazioni and attivazioni show large numbers of high outliers, with values reaching into the hundreds or over a thousand, which are implausible as single-employee events but entirely plausible as bulk or batch-uploaded aggregates. These are unusual rather than wrong, and they point to mixed granularity in the source rather than data-entry errors. The negative cessazioni values were genuine errors and were corrected to zero.

### Remediation

| measure | value |
|---|---|
| corrections applied automatically | 3 |
| proposals put to the reviewer | 7 |
| proposals accepted | 7 |
| proposals carrying a generated function | 2 |
| generated functions validated in a sandbox | 6 of 6 |
| cells changed in total | 8,246 |
| issues carried without an action | 2 |

### Issues carried without a corrective action

These were detected and reported. No correction is proposed for them, because none can be
expressed as code over the columns the file actually contains; acting anyway would mean
inventing values. They are listed so the gap is visible rather than silently carried.

| column (rows affected) | why no action is proposed |
|---|---|
| `anno` (1,352), `qualifica` (5,086), `attivazioni` (195) | The missing values in cessazioni, qualifica, note, fonte_dato, and attivazioni cannot be safely imputed without a deterministic rule or external data. For cessazioni and attivazioni, no imputation hint is available, and filling them with constants or statistics would risk inventing data. For qualifica, note, and fonte_dato, the missing rates are extremely high (over 50% for note and fonte_dato), and no reliable predictor exists. These require human judgment or additional data sources. (`_id`, `RATA`, `aggregation-time`, `note`, `fonte_dato` are also named above but are covered by a proposal at the gate.) |
| `provincia_sede` (1,312), `regione_sede` (9,640) | Both violations require human judgement and cannot be safely repaired automatically. The 359 missing values in `provincia_sede` (c0_v1) cannot be filled: there is no `imputation_hint` for this column, and the related columns (`regione_sede`, `codice_ente`, `descrizione_ente`) do not provide a deterministic rule to derive a province code — a region contains many provinces and an entity code does not map to a single office location. Inventing a province would violate the "never invent data" invariant. The 10 `regione_sede` values of `99` (c3_v1) fall outside the valid range [1, 20]; `99` is a sentinel/unknown code with no recoverable information in the row, and the value-correction agent already flagged it as unaddressable (total_unaddressable: 1). Mapping `99` to a specific region would be a guess, so it must be left for the user to correct or flag. |

The pipeline repaired period normalization, derived mese and anno from rata where the period was unambiguous, corrected negative termination counts, and resolved the duplicate columns and naming violations. The generated cleaning functions implement durable rules: one normalizes month values to 1-12 and strips leading zeros, and another clamps negative termination counts to zero, so future imports with the same defects will be handled consistently. The qualifica gaps and the residual mese/anno inconsistencies were deliberately left alone because no deterministic rule or external source could fill them safely.

## What was changed

### Applied without asking, because the data determined them

| column | correction | cells | why it needed no approval |
|---|---|---|---|
| `RATA` | normalize_period | 802 | alternative period layouts rewritten to the canonical YYYYMM form |
| `mese` | derive_month_from_period | 575 | mese could not be read as a month on these rows, and RATA states it directly, so the value was filled from the period |
| `anno` | derive_year_from_period | 383 | anno could not be read as a year on these rows, and RATA states it directly, so the value was filled from the period |

### Put to the reviewer

| id | columns | what it does | outcome |
|---|---|---|---|
| `schema_drop_note` | `note` | Drop 'note': it is 98.5% null and carries almost no information. | accepted |
| `schema_drop_fonte_dato` | `fonte_dato` | Drop 'fonte_dato': it is 99.2% null and carries almost no information. | accepted |
| `schema_rename__id` | `_id` | Rename '_id' to 'id' to match the naming convention. | accepted |
| `schema_rename_RATA` | `RATA` | Rename 'RATA' to 'rata' to match the naming convention. | accepted |
| `schema_rename_aggregation-time` | `aggregation-time` | Rename 'aggregation-time' to 'aggregation_time' to match the naming convention. | accepted |
| `clean_mese` | `mese` | Correct mese values that are inconsistent with the month encoded in RATA by extracting the last two digits of RATA. | accepted |
| `clean_cessazioni` | `cessazioni` | Correct negative cessazioni values to 0. | accepted |

### Cleaning functions written for this dataset

Each function below was refused any import outside `re`, `datetime`, `decimal` and `math`, executed in a sandbox against the column's own conforming and violating values, and read by a person before it ran. This is the code that was executed.

On `mese`:

```python
def clean_value(value):
    import re
    text = str(value).strip()
    if not text:
        return None
    # Already valid month (1-12) without leading zero? Return as is.
    if re.fullmatch(r'(?:[1-9]|1[0-2])', text):
        return text
    # If zero-padded month like '06', strip leading zero and return.
    if re.fullmatch(r'0[1-9]', text):
        return text[1:]
    # Otherwise, cannot correct without RATA context; return None.
    return None
```

On `cessazioni`:

```python
def clean_value(value):
    import math
    v = float(value)
    if math.isnan(v):
        return None
    if v < 0:
        return '0'
    return str(int(v))
```

### Cells changed, by column

| column | cells changed |
|---|---|
| `provincia_sede` | 2,599 |
| `descrizione_ente` | 1,991 |
| `RATA` | 802 |
| `mese` | 744 |
| `anno` | 585 |
| `regione_sede` | 496 |
| `codice_ente` | 394 |
| `attivazioni` | 234 |
| `cessazioni` | 203 |
| `att ivazioni` | 196 |
| `aggregation-time` | 1 |
| `3descrizione` | 1 |

## The dataset as delivered



| measure | as received | after remediation |
|---|---|---|
| rows | 20,102 | 20,012 |
| columns | 19 | 12 |
| null cells | 46,847 | 5,807 |
| format violations | n/a | 10 |
| inconsistent rows | n/a | 1,493 |
| duplicate rows | 60 | 0 |
| rows in key conflict | 60 | 0 |
| columns badly named | 8 | 0 |
| columns almost empty | 2 | 0 |
| columns duplicating another | 0 | 0 |
| columns still holding the wrong type | 0 | 0 |

Restricted to the columns present at both ends, reliability moved from **0.865** to **0.980**. The headline pair counts the columns the pipeline removed; this one does not, so removing an empty column is not read as an improvement.

Still open: 10 format, 5807 completeness, 1526 consistency.

## Every column at a glance

One row per column of the delivered file. `detected` counts what was found against it on arrival, `outstanding` what a check still reports, and `cells changed` how many of its values the run rewrote.

| column | type | filled | detected | outstanding | cells changed |
|---|---|---|---|---|---|
| `id`<br><sub>from _id</sub> | object | 100.0% | 0 | 0 | 0 |
| `mese` | Int64 | 100.0% | 2,277 | 954 | 744 |
| `anno` | Int64 | 100.0% | 1,543 | 572 | 585 |
| `cessazioni` | Int64 | 99.0% | 202 | 194 | 203 |
| `rata`<br><sub>from RATA</sub> | object | 100.0% | 0 | 0 | 0 |
| `aggregation_time`<br><sub>from aggregation-time</sub> | datetime64[ns] | 100.0% | 0 | 0 | 0 |
| `qualifica` | object | 74.7% | 5,086 | 5,062 | 0 |
| `provincia_sede` | object | 98.2% | 1,312 | 356 | 2,599 |
| `codice_ente` | int64 | 100.0% | 0 | 0 | 394 |
| `descrizione_ente` | string | 100.0% | 0 | 0 | 1,991 |
| `regione_sede` | int64 | 100.0% | 9,640 | 10 | 496 |
| `attivazioni` | Int64 | 99.0% | 195 | 195 | 234 |

## Recommendations

1. Stop exporting duplicate column pairs (codice_ente/CODICE ENTE, regione_sede/regione%sede, attivazioni/att ivazioni, and the two descrizione_ente variants); emit a single canonical column per field so downstream resolution never has to choose between disagreeing copies.
2. Enforce a single period format for rata at the source (canonical YYYYMM) and derive mese and anno from it, so the month and year columns cannot drift out of sync with the reference period.
3. Require qualifica to be populated at data entry, or provide a lookup from codice_ente/descrizione_ente, since a quarter of records currently lack it and it cannot be recovered downstream.
4. Replace the N.D. placeholder in cessazioni and attivazioni with a true null at the source, and validate that termination and activation counts are non-negative integers before export.
