# Baseline Builder Prompt

## Task
Given a dataset from the NoiPA Italian Public Administration portal, assign it to one of the following thematic domains:

- `Amministrati` — demographic data on persons administered by NoiPA; counts segmented by geography, age, sex, and access/payment modality
- `Amministrazioni` — organizational-structure data on the PA entities served by NoiPA; counts of organizational units and working relationships segmented by workplace location, administration, and employee demographics
- `Rapporti_di_lavoro` — working-relationship data on employment contracts binding administered persons to PA entities; counts segmented by workplace province, employing administration, demographics, contractual classification, and contract lifecycle reasons
- `Trattamento_economico` — financial and tax-treatment data on salary disbursements; payslip-level fiscal and social-security withholdings, family allowances, income-bracket distributions, absences affecting compensation, trade-union/loan deductions, and annual Certificazione Unica totals

## Signal priority

Use signals in this order — stop as soon as one is conclusive:

### 1. Filename (strongest signal)
All NoiPA files follow the pattern `Entry<DatasetName>_YYYYMM.csv` or `Entry<DatasetName>_YYYY.csv`. The dataset name maps directly to a domain:

| Dataset name | Domain |
|---|---|
| EntryAmministrati, EntryResidenti, EntryPendolarismo, EntryAccessoAmministrati, EntryAccreditoStipendi | `Amministrati` |
| EntryStrutturaOrganizzativa | `Amministrazioni` |
| EntryContrattiGestiti, EntryInquadramenti, EntryMotivoAssunzione, EntryMotivoCessazione | `Rapporti_di_lavoro` |
| EntryCertificazioniUniche, EntryAmministratiPerFasciaDiReddito, EntryAssegniFamiliari, EntryAssenzeContabilizzate, EntryCedolinoRitenuteFiscali, EntryCedolinoRitenutePrevidenziali, EntryDetrazioniFamiliari, EntryRitenutePrestiti, EntryRitenuteSindacali | `Trattamento_economico` |

If the filename matches any entry in this table, return that domain immediately without consulting column names or sample values.

### 2. Distinctive columns
The following columns are exclusive to their domain — their presence is conclusive:

- `Amministrati`: `modalita_autenticazione`, `modalita_pagamento`, `stesso_comune`, `distance_min_KM`, `distance_max_KM`, `numero_occorrenze`, `regione_residenza_domicilio`
- `Amministrazioni`: `numero_unita_organizzative`, `numero_rapporti_lavoro`
- `Rapporti_di_lavoro`: `comparto`, `inquadramento`, `motivo_assunzione`, `motivo_cessazione`
- `Trattamento_economico`: `importo`, `imponibile_fiscale`, `importo_IRPEF`, `ritenuta_previdenziale`, `numero_cedolini`, `fascia_reddito_min`, `fascia_reddito_max`, `aliquota_max`, `imponibili_previdenziali`, `reddito_relativo_anno_corrente`, `reddito_relativo_anni_precedenti`, `detrazioni_coniuge`, `detrazioni_figli`, `detrazioni_altri_familiari`, `previdenza_complementare`, `motivazione_assenza`, `granularita_assenza`, `importo_lavoratore`, `importo_datore`, `importo_ritenute`, `numero_ritenute`, `anno`

### 3. Sample values (weakest signal)
Use only when neither filename nor distinctive columns are present. Monetary amounts, tax figures, and fiscal codes strongly suggest `Trattamento_economico`; organizational unit counts suggest `Amministrazioni`.

## Columns that are NOT discriminating
The following columns appear across all four domains — ignore them for classification:
`comune_della_sede`, `provincia_della_sede`, `provincia_di_residenza`, `amministrazione`, `amministrazione_appartenenza`, `ente`, `eta_min`, `eta_max`, `sesso`, `numero`, `numero_amministrati`, `regione_residenza`

## Input
Dataset column names, an optional filename, and a sample of values (first 50 rows).

## Output
The `domain` value must be copied exactly as written above — same casing, same underscores. Any deviation will break the downstream registry lookup.

Return a JSON object:
```json
{
  "domain": "<one of: Amministrati | Amministrazioni | Rapporti_di_lavoro | Trattamento_economico>",
  "rationale": "<one sentence naming the decisive signal used>"
}
```
