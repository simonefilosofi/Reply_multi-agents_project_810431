# Example datasets

Synthetic NoiPA-style fixtures used by the test suite and the demo dashboard.
All three CSVs are produced by `_generate.py` and are byte-stable across runs
(`numpy.random.default_rng(seed=42)`). To regenerate after editing the
builders:

```bash
python data/examples/_generate.py
```

| File | Rows | Cols | Purpose |
| --- | --- | --- | --- |
| `clean_noipa_sample.csv` | 120 | 6 | Canonical, lint-clean payroll slice. Used as the high-baseline reliability case. |
| `dirty_noipa_sample.csv` | 508 | 6 | Same six-column schema with every detector-firing pattern injected. Used as the primary acceptance fixture. |
| `large_synthetic.csv` | 5000 | 6 | Scale-up of the dirty schema for performance smoke tests. |

## Schema

All three datasets share the same six fields:

- `rata` — payroll period code. In the clean file: `YYYYMM` (raw input). In the
  dirty files: a mix of `YYYYMM`, `YYYY-MM`, `MON-YYYY`, `MM/YYYY`, free text
  ("Rata 2024"), invalid month codes (`202413`, `202499`), and two-digit-year
  variants (`05/24`). After `normalize_period_column` runs, the canonical form
  is `MM-YYYY`.
- `ente` — issuing public entity. In the dirty files: 8 % placeholders
  (`N.D.`, `n.a.`, `sconosciuto`, `non disponibile`, blank).
- `descrizione` — free-text payroll description. In the dirty files: 4 % of
  rows have an `" x"` suffix (placeholder pattern).
- `tipo_imposta` — tax-type code. In the dirty files: 15 % case mixing
  (`IRPEF` / `irpef` / `Irpef`), occasional `n.c.` placeholder, two
  rare-category injections (`ZZZ_RARE`).
- `imposta` — tax amount. In the dirty files: 10 % `\u20ac`-prefixed currency
  strings, 10 % Italian comma-decimals (`1.234,56`), 3 % `N.D.` placeholders
  and 2 % negative values (domain violations).
- `spesa` — total spend. In the dirty files: 1 % outliers (50–200x normal
  range) and 5 % nulls.

## Issue coverage

Together the three files exercise every issue type in
`state_demo.constants.ISSUE_TYPES`. The dirty files also include 8 fully
duplicated rows (`duplicate_rows`), and the wide-dirty pytest fixture in
`tests/conftest.py` (built by the same module) carries 30 columns covering
sparse columns, value-duplicate columns, semantic-duplicate columns,
conditional completeness and lookup imputability.
