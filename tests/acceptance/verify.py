"""Regression net for pipeline runs over the two client datasets. Pins value-level invariants -
what was recovered, what was merged, what was overwritten - rather than the output bytes, because
the LLM nodes are not reproducible run to run and a byte diff would report model noise as a
regression. It reads a recorded run under reports/runs/ and its report payload, so it needs no network and
no key. Run with --pin to record the current run as the baseline, with no argument to compare a
later run against it.

    python tests/acceptance/verify.py --pin      record the current runs as the baseline
    python tests/acceptance/verify.py            compare a later run against it
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PINNED = Path(__file__).resolve().parent / "invariants.json"

MESI = {"GEN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAG": 5, "GIU": 6,
        "LUG": 7, "AGO": 8, "SET": 9, "OTT": 10, "NOV": 11, "DIC": 12}

DATASETS = {
    "spesa": {
        "raw": ROOT / "data/raw/project_data_quality/spesa.csv",
        "run": ROOT / "reports/runs/spesa",
        "id_raw": "_id", "id_final": "id",
        "numeric_pairs": [("SPESA TOTALE", "spesa"), ("ente%code", "ente"),
                          ("2cod_imposta", "cod_imposta")],
        "date_pair": ("aggregation-time", "aggregation_time"),
        "period_column": "rata",
        "period_authority": None,
    },
    "attivazioniCessazioni": {
        "raw": ROOT / "data/raw/project_data_quality/attivazioniCessazioni.csv",
        "run": ROOT / "reports/runs/attivazioniCessazioni",
        "id_raw": "_id", "id_final": "id",
        "numeric_pairs": [("att ivazioni", "attivazioni"), ("cessazioni", "cessazioni"),
                          ("CODICE ENTE", "codice_ente")],
        "date_pair": ("aggregation-time", "aggregation_time"),
        "period_column": "rata",
        "period_authority": {"raw_period": "RATA", "month": "mese", "year": "anno"},
    },
}


def expected_numeric(value) -> float | None | str:
    """What a correct cleaner should produce for one raw messy value."""
    text = str(value).strip()
    if text.lower() in ("n.d.", "nd", "unknown", "?", "-", "//", "", "na", "n/a"):
        return None
    text = text.replace("€", "").replace("EUR", "").strip()
    text = re.sub(r"\s*unit[aà]\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*giorni\s*$", "", text, flags=re.I)
    if re.fullmatch(r"-?\d+,\d+", text):
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return "UNPARSEABLE"


def expected_date(value) -> tuple[int, int, int] | None:
    text = str(value).strip()
    for pattern, order in ((r"(\d{2})/(\d{2})/(\d{4})", (3, 2, 1)),
                           (r"(\d{2})\.(\d{2})\.(\d{4})", (3, 2, 1)),
                           (r"(\d{4})/(\d{2})/(\d{2})", (1, 2, 3))):
        found = re.fullmatch(pattern, text)
        if found:
            return tuple(int(found.group(g)) for g in order)
    found = re.fullmatch(r"(\d{2})-(\d{2})-(\d{2})", text)
    if found:
        return (2000 + int(found.group(3)), int(found.group(2)), int(found.group(1)))
    found = re.fullmatch(r"([A-Z]{3}) (\d{2}) (\d{4})", text)
    if found:
        return (int(found.group(3)), MESI[found.group(1)], int(found.group(2)))
    return None


def cleaned_dataset(config: dict) -> Path:
    """The delivered file of a recorded run, which report_generator writes beside the report."""
    run = config["run"]
    return run / f"{run.name}.cleaned.csv"


def aligned(config: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(config["raw"]).drop_duplicates(subset=config["id_raw"]).set_index(config["id_raw"])
    final = pd.read_csv(cleaned_dataset(config))
    final = final.drop_duplicates(subset=config["id_final"]).set_index(config["id_final"])
    common = raw.index.intersection(final.index)
    return raw.loc[common], final.loc[common]


def numeric_recovery(raw: pd.DataFrame, final: pd.DataFrame, pairs) -> dict:
    out = {}
    for raw_column, final_column in pairs:
        if raw_column not in raw.columns or final_column not in final.columns:
            out[f"{raw_column}->{final_column}"] = {"status": "column missing"}
            continue
        source, result = raw[raw_column], final[final_column]
        messy = source[pd.to_numeric(source, errors="coerce").isna() & source.notna()]
        ok = wrong = lost = 0
        for index, value in messy.items():
            want, got = expected_numeric(value), result.loc[index]
            if want == "UNPARSEABLE":
                continue
            if want is None:
                ok += 1 if pd.isna(got) else 0
                wrong += 0 if pd.isna(got) else 1
            elif pd.isna(got):
                lost += 1
            elif abs(float(got) - want) < 0.011:
                ok += 1
            else:
                wrong += 1
        out[f"{raw_column}->{final_column}"] = {"messy": len(messy), "ok": ok,
                                                "wrong": wrong, "lost": lost}
    return out


def date_recovery(raw: pd.DataFrame, final: pd.DataFrame, pair) -> dict:
    raw_column, final_column = pair
    if raw_column not in raw.columns or final_column not in final.columns:
        return {"status": "column missing"}
    parsed = pd.to_datetime(final[final_column], errors="coerce")
    ok = wrong = 0
    for index, value in raw[raw_column].items():
        want = expected_date(value)
        if want is None:
            continue
        got = parsed.loc[index]
        if not pd.isna(got) and (got.year, got.month, got.day) == want:
            ok += 1
        else:
            wrong += 1
    return {"checked": ok + wrong, "ok": ok, "wrong": wrong}


def authority_overwrites(raw: pd.DataFrame, final: pd.DataFrame, spec: dict | None) -> dict:
    """Counts cells that were well formed on arrival and were rewritten anyway because a period
    key disagreed with them. This is the F1 metric: the deduction is legitimate where the target
    is malformed, and a silent judgement call where both sides parse cleanly."""
    if not spec:
        return {"applicable": False}
    month_raw = pd.to_numeric(raw[spec["month"]], errors="coerce")
    year_raw = pd.to_numeric(raw[spec["year"]], errors="coerce")
    period_raw = pd.to_numeric(raw[spec["raw_period"]], errors="coerce")
    month_ok = month_raw.notna() & (month_raw % 1 == 0) & month_raw.between(1, 12)
    year_ok = year_raw.notna() & (year_raw % 1 == 0) & year_raw.between(1900, 2100)
    return {
        "applicable": True,
        "rows_with_well_formed_month": int(month_ok.sum()),
        "rows_with_well_formed_year": int(year_ok.sum()),
        "clean_month_overwritten": int((month_ok & (month_raw != final[spec["month"]])).sum()),
        "clean_year_overwritten": int((year_ok & (year_raw != final[spec["year"]])).sum()),
        "clean_month_overwritten_while_period_also_clean":
            int((month_ok & period_raw.notna() & (month_raw != final[spec["month"]])).sum()),
        "malformed_month_filled": int((~month_ok & raw[spec["month"]].notna()
                                       & final[spec["month"]].notna()).sum()),
        "malformed_year_filled": int((~year_ok & raw[spec["year"]].notna()
                                      & final[spec["year"]].notna()).sum()),
    }


def auto_path_behaviour(payload: dict) -> dict:
    """What the deterministic path settled on its own, which the delivered file cannot answer:
    a rewrite the auto path now declines may still arrive through an approved proposal, which is
    the intended route and not a regression. The mined rules carry that distinction directly -
    rows_breaking is what the file arrived with, rows_remaining what no stage could repair."""
    derivations = {entry["operation"]: entry["cells_changed"]
                   for entry in payload["auto_remediations"]
                   if entry["operation"].startswith("derive_")}
    contested = {rule["rule"]: [rule["rows_breaking"], rule["rows_remaining"]]
                 for rule in payload.get("cross_column_rules") or []}
    return {"derive_cells_changed": derivations, "cross_column_rules": contested}


def measure(name: str, config: dict) -> dict:
    run = config["run"]
    payload = json.loads((run / f"{run.name}.json").read_text(encoding="utf-8"))
    raw, final = aligned(config)
    full_final = pd.read_csv(cleaned_dataset(config))
    resolutions = payload["duplicate_resolutions"]
    groups = sorted(tuple(sorted(r["group"])) for r in resolutions)
    period = full_final[config["period_column"]].dropna().astype(str)
    return {
        "input_shape": [payload["quality"]["snapshots"]["raw"]["rows"],
                        payload["quality"]["snapshots"]["raw"]["columns"]],
        "final_shape": [int(full_final.shape[0]), int(full_final.shape[1])],
        "final_columns": sorted(full_final.columns),
        "errors": payload["errors"],
        "numeric_recovery": numeric_recovery(raw, final, config["numeric_pairs"]),
        "date_recovery": date_recovery(raw, final, config["date_pair"]),
        "duplicate_groups": [list(g) for g in groups],
        "duplicate_canonical_names": sorted(r["canonical_name"] for r in resolutions),
        "note_fonte_dato_merged": any(
            {"note", "fonte_dato"} <= set(r["group"]) for r in resolutions),
        "final_nulls_per_column": {c: int(full_final[c].isna().sum()) for c in sorted(full_final.columns)},
        "period_all_canonical": bool(period.str.fullmatch(r"\d{6}").all()),
        "authority_overwrites": authority_overwrites(raw, final, config["period_authority"]),
        "auto_path_behaviour": auto_path_behaviour(payload),
        "rows_removed_as_duplicates": (payload.get("duplicate_rows") or {}).get("rows_removed"),
    }


def flatten(prefix: str, value, into: dict) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            flatten(f"{prefix}.{key}" if prefix else str(key), item, into)
    else:
        into[prefix] = value


def compare(pinned: dict, current: dict) -> int:
    failures = 0
    for name in sorted(set(pinned) | set(current)):
        if name not in pinned:
            print(f"[NEW ] {name}: not in the baseline")
            continue
        if name not in current:
            print(f"[MISS] {name}: absent from this run")
            failures += 1
            continue
        before, after = {}, {}
        flatten("", pinned[name], before)
        flatten("", current[name], after)
        changed = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
        if not changed:
            print(f"[ OK ] {name}: {len(before)} invariants unchanged")
            continue
        print(f"[DIFF] {name}: {len(changed)} of {len(before)} invariants changed")
        for key in changed:
            print(f"         {key}\n           baseline: {before.get(key)!r}\n           now     : {after.get(key)!r}")
        failures += len(changed)
    return failures


def main() -> int:
    current = {name: measure(name, config) for name, config in DATASETS.items()
               if (config["run"] / f"{config['run'].name}.json").exists()}
    if "--pin" in sys.argv:
        PINNED.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
        for name, values in current.items():
            print(f"pinned {name}: {json.dumps(values['numeric_recovery'], ensure_ascii=False)}")
            print(f"        dates {values['date_recovery']}  authority {values['authority_overwrites']}")
        print(f"\nbaseline written to {PINNED}")
        return 0
    if not PINNED.exists():
        print("no baseline pinned; run with --pin first")
        return 2
    pinned = json.loads(PINNED.read_text(encoding="utf-8"))
    failures = compare(pinned, current)
    print()
    print("REGRESSION CHECK PASSED" if failures == 0 else f"REGRESSION CHECK FAILED: {failures} changed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
