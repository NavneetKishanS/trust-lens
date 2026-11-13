"""Synthetic type-2 diabetes cohort across 3 laboratories, with SEEDED DEFECTS.

Every defect we inject is written to seeded_defects.csv. That file is the ground
truth for the eval harness: the validation engine must find these, and we report
recall/precision live in the demo.

Run:  python data/generate.py        (writes CSVs into data/out/)
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
OUT = Path(__file__).parent / "out"
N_PATIENTS = 240
START = date(2024, 1, 1)
END = date(2026, 9, 30)

LOINC_HBA1C_PCT = "4548-4"       # HbA1c / Hb.total in Blood (%)
LOINC_HBA1C_IFCC = "59261-8"     # HbA1c / Hb.total in Blood, IFCC (mmol/mol)
LOINC_GLUCOSE = "2345-7"         # Glucose in serum/plasma (wrong test!)

LABS = [
    # lab_id, name, default unit, default method, loinc
    ("LAB_A", "Uniklinikum Labor Nord", "mmol/mol", "HPLC", LOINC_HBA1C_IFCC),
    ("LAB_B", "MVZ Labordiagnostik Mitte", "mmol/mol", "HPLC", LOINC_HBA1C_IFCC),
    ("LAB_C", "Praxislabor Süd", "%", "Immunoassay", LOINC_HBA1C_PCT),
]

FIRST = ["Anna", "Lukas", "Mia", "Leon", "Emma", "Paul", "Lea", "Jonas", "Sofia", "Felix",
         "Marie", "Elias", "Hannah", "Noah", "Lina", "Ben", "Emilia", "Finn", "Clara", "Max"]
LAST = ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker",
        "Schulz", "Hoffmann", "Koch", "Richter", "Klein", "Wolf", "Neumann", "Braun"]
DRUGS = [("Metformin", "1000 mg BID"), ("Empagliflozin", "10 mg QD"),
         ("Sitagliptin", "100 mg QD"), ("Insulin glargine", "14 IU QHS"),
         ("Semaglutide", "0.5 mg weekly")]
SYMPTOMS = ["fatigue", "polyuria", "thirst", "blurred vision", "tingling feet",
            "slow wound healing", "dizziness", "nausea", "night sweats", "itchy skin"]
RARE_SYMPTOMS = ["metallic taste", "hair thinning", "vivid dreams"]


def pct_to_ifcc(pct: float) -> float:
    return round(10.929 * pct - 23.5, 1)


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)

    labs, patients, results, encounters, meds, reports, defects = [], [], [], [], [], [], []

    for lab_id, name, unit, method, loinc in LABS:
        labs.append(dict(lab_id=lab_id, name=name, default_unit=unit,
                         default_method=method, loinc_code=loinc, accreditation="DAkkS ISO 15189"))

    def defect(dtype: str, check: str, lab_id: str, desc: str) -> None:
        defects.append(dict(defect_id=f"D{len(defects)+1:02d}", defect_type=dtype,
                            expected_check=check, lab_id=lab_id, description=desc))

    # ---- patients -------------------------------------------------------
    for i in range(N_PATIENTS):
        pid = f"P{i+1:04d}"
        lab_id = LABS[i % 3][0]
        # DEFECT: LAB_C population skew — only older patients
        birth_year = rng.randint(1940, 1964) if lab_id == "LAB_C" else rng.randint(1945, 1995)
        patients.append(dict(patient_id=pid, display_name=f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                             sex=rng.choice(["F", "M"]), birth_year=birth_year,
                             diagnosis_code="E11.9", diagnosis="Type 2 diabetes mellitus",
                             home_lab_id=lab_id, source_system=f"KIS-{lab_id[-1]}"))

    # ---- lab results ----------------------------------------------------
    rid = 0
    for p in patients:
        lab_id = p["home_lab_id"]
        _, _, unit, method, loinc = next(l for l in LABS if l[0] == lab_id)
        base_pct = rng.uniform(6.4, 9.6)
        trend = rng.uniform(-0.04, 0.01)  # most improve slowly on therapy
        d = START + timedelta(days=rng.randint(0, 60))
        k = 0
        while d <= END:
            pct = max(5.2, base_pct + trend * k * 3 + rng.gauss(0, 0.25))
            row_method = method
            row_loinc = loinc
            specimen = "whole blood (EDTA)"
            value: float | None = round(pct, 1) if unit == "%" else pct_to_ifcc(pct)
            # DEFECT: LAB_B switches method mid-2025
            if lab_id == "LAB_B" and d >= date(2025, 7, 1):
                row_method = "Immunoassay"
            # DEFECT: LAB_C has no results Jul–Sep 2025 (analyser outage)
            if lab_id == "LAB_C" and date(2025, 7, 1) <= d < date(2025, 10, 1):
                d += timedelta(days=rng.randint(80, 110)); k += 1
                continue
            # DEFECT: LAB_B ~18% missing values
            if lab_id == "LAB_B" and rng.random() < 0.18:
                value = None
            # DEFECT: LAB_A a few rows coded as glucose
            if lab_id == "LAB_A" and rng.random() < 0.04:
                row_loinc = LOINC_GLUCOSE
            # DEFECT: LAB_C some serum specimens (invalid for HbA1c)
            if lab_id == "LAB_C" and rng.random() < 0.06:
                specimen = "serum"
            rid += 1
            row = dict(result_id=f"R{rid:06d}", patient_id=p["patient_id"], lab_id=lab_id,
                       loinc_code=row_loinc, test_name="HbA1c", result_value=value, result_unit=unit,
                       lab_method=row_method, specimen=specimen, collected_at=d.isoformat(),
                       source_file=f"{lab_id.lower()}_export_{d.year}.hl7", source_row=rid)
            results.append(row)
            # DEFECT: LAB_A duplicates (double-imported HL7 messages)
            if lab_id == "LAB_A" and rng.random() < 0.03:
                rid += 1
                dup = dict(row, result_id=f"R{rid:06d}", source_row=rid)
                results.append(dup)
            d += timedelta(days=rng.randint(80, 110)); k += 1

    # DEFECT: implausible values (unit entry error)
    for r in rng.sample([r for r in results if r["lab_id"] == "LAB_B" and r["result_value"] is not None], 4):
        r["result_value"] = round(r["result_value"] * 10, 1)

    defect("unit_heterogeneity", "unit_consistency", "LAB_C",
           "LAB_C reports HbA1c in % (NGSP); LAB_A/LAB_B use mmol/mol (IFCC).")
    defect("method_change", "method_comparability", "LAB_B",
           "LAB_B switched from HPLC to immunoassay on 2025-07-01.")
    defect("time_gap", "time_coverage", "LAB_C", "LAB_C has no HbA1c results Jul–Sep 2025.")
    defect("missing_values", "completeness", "LAB_B", "~18% of LAB_B HbA1c values are NULL.")
    defect("wrong_test_code", "test_consistency", "LAB_A",
           "~4% of LAB_A 'HbA1c' rows carry the glucose LOINC 2345-7.")
    defect("invalid_specimen", "specimen_consistency", "LAB_C",
           "~6% of LAB_C HbA1c rows are on serum (requires whole blood).")
    defect("duplicates", "duplicates", "LAB_A", "~3% of LAB_A rows are double-imported.")
    defect("implausible_values", "plausibility", "LAB_B",
           "4 LAB_B values multiplied by 10 (decimal entry error).")
    defect("population_skew", "population_coverage", "LAB_C",
           "LAB_C patients are all born before 1965 (age skew).")

    # ---- encounters, notes, meds (for physician/patient views) ----------
    eid = 0
    for p in patients:
        d = START + timedelta(days=rng.randint(0, 90))
        visits = 0
        drug, dose = rng.choice(DRUGS)
        meds.append(dict(rx_id=f"RX{len(meds)+1:05d}", patient_id=p["patient_id"], drug=drug, dose=dose,
                         start_date=d.isoformat(), end_date="", prescriber="Dr. Weber",
                         source_file="ehr_prescriptions.fhir.json"))
        while d <= END and visits < 8:
            eid += 1
            sym = rng.sample(SYMPTOMS, 2)
            note = (f"Follow-up for T2DM. Patient reports {sym[0]} and {sym[1]}. "
                    f"Adherent to {drug}. Advised diet review; recheck HbA1c in 3 months.")
            if visits == 4 and rng.random() < 0.4:
                drug2, dose2 = rng.choice([x for x in DRUGS if x[0] != drug])
                note += f" Added {drug2} {dose2}."
                meds.append(dict(rx_id=f"RX{len(meds)+1:05d}", patient_id=p["patient_id"], drug=drug2,
                                 dose=dose2, start_date=d.isoformat(), end_date="",
                                 prescriber="Dr. Weber", source_file="ehr_prescriptions.fhir.json"))
            encounters.append(dict(encounter_id=f"E{eid:06d}", patient_id=p["patient_id"],
                                   encounter_date=d.isoformat(), encounter_type="outpatient",
                                   clinician="Dr. Weber", note_text=note,
                                   source_file="ehr_notes.fhir.json"))
            d += timedelta(days=rng.randint(70, 140)); visits += 1

        # patient-reported symptoms (community) — all start PENDING clinician review
        for _ in range(rng.randint(0, 3)):
            s = rng.choice(RARE_SYMPTOMS) if rng.random() < 0.08 else rng.choice(SYMPTOMS)
            reports.append(dict(report_id=f"PR{len(reports)+1:05d}", patient_id=p["patient_id"],
                                symptom=s, severity=rng.randint(1, 5),
                                note_text=f"Noticed {s} this week.", what_helped=rng.choice(
                                    ["walking after meals", "less bread", "nothing yet", "more water", ""]),
                                reported_at=(END - timedelta(days=rng.randint(0, 60))).isoformat(),
                                review_status="pending"))

    def write(name: str, rows: list[dict]) -> None:
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)

    write("labs", labs); write("patients", patients); write("lab_results", results)
    write("encounters", encounters); write("medications", meds)
    write("patient_reports", reports); write("seeded_defects", defects)
    print(f"patients={len(patients)} results={len(results)} encounters={len(encounters)} "
          f"meds={len(meds)} reports={len(reports)} defects={len(defects)} -> {OUT}")


if __name__ == "__main__":
    main()
