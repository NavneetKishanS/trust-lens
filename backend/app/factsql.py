"""Run db/facts.sql for one patient and pack the rows into facts (Dev A).

Dev B's clinical/facts.py calls compute_facts() and stores the result in clinical.facts with FCT- IDs:

    from app.factsql import compute_facts
    for f in compute_facts(patient_id):
        f["block"]           # 'lab_trend'  -> lineage transform 'facts.sql:lab_trend'
        f["kind"]            # 'LAB_TREND'
        f["data"]            # dict, e.g. {"loinc": "2339-0", "latest": {"value": 91, "date": "2025-10-02", "flag": "NORMAL"}, ...}
        # sort_* columns only order the rows and are not part of the data
        f["data_json"]       # same, canonical JSON text for clinical.facts.data_json
        f["source_row_ids"]  # ['OBS-0004411', 'OBS-0005120'] (store ','.join(...) in clinical.facts)

CLI:  python -m app.factsql <patient_id>        # print the facts as JSON
      python -m app.factsql --check 5           # 5 random patients: every source row ID must exist
"""
from __future__ import annotations

import json
import re
import random
import sys

from .db import DB, get_db

FACTS_SQL = "db/facts.sql"
BLOCK_ORDER = ["lab_trend", "condition", "medication", "immunization", "encounter", "careplan", "allergy",
               "next_step"]

# Row ID prefix -> curated table (shared §5)
ROW_TABLES = {
    "PAT": "curated.patients", "ENC": "curated.encounters", "CON": "curated.conditions",
    "OBS": "curated.observations", "MED": "curated.medications", "IMM": "curated.immunizations",
    "CPL": "curated.careplans", "ALG": "curated.allergies",
}


def _num(v):
    """Integral floats become ints so 91.0 is written as 91."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def tables_in(sql: str) -> list[str]:
    """schema.table names a block reads (curated.* / ref.*)."""
    return sorted(set(re.findall(r"\b((?:curated|ref)\.[a-z_]+)\b", sql)))


def pack_row(row: dict) -> dict:
    """{'kind', 'source_row_ids', 'a', 'b__c', 'opt_d', 'sort_x', ...} -> {'kind', 'source_row_ids': [...], 'data': {...}}
    b__c nests, opt_d is dropped when NULL, sort_x is ordering only (see the header of db/facts.sql)."""
    data: dict = {}
    groups: dict[str, dict] = {}
    for col, val in row.items():
        if col in ("kind", "source_row_ids") or col.startswith("sort_"):
            continue
        if "__" in col:
            outer, inner = col.split("__", 1)
            groups.setdefault(outer, {})[inner] = _num(val)
        elif col.startswith("opt_"):
            if val is not None:
                data[col[4:]] = _num(val)
        else:
            data[col] = _num(val)
    for outer, fields in groups.items():
        data[outer] = fields if any(v is not None for v in fields.values()) else None
    ids = [s.strip() for s in (row.get("source_row_ids") or "").split(",") if s.strip()]
    return {"kind": row["kind"], "data": data, "source_row_ids": ids}


def compute_facts(patient_id: str, db: DB | None = None, blocks: list[str] | None = None) -> list[dict]:
    db = db or get_db()
    sql_blocks = DB.named_blocks(FACTS_SQL)
    facts = []
    for name in blocks or BLOCK_ORDER:
        sql = sql_blocks[name]
        for row in db.query(sql, [patient_id] * sql.count("?")):
            f = pack_row(row)
            f["block"] = name
            f["data_json"] = json.dumps(f["data"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            facts.append(f)
    return facts


def missing_row_ids(facts: list[dict], db: DB | None = None) -> list[str]:
    db = db or get_db()
    by_table: dict[str, set] = {}
    for f in facts:
        for rid in f["source_row_ids"]:
            by_table.setdefault(ROW_TABLES.get(rid.split("-")[0], "?"), set()).add(rid)
    missing = []
    for table, ids in by_table.items():
        if table == "?":
            missing += sorted(ids)
            continue
        ids = sorted(ids)
        marks = ", ".join("?" for _ in ids)
        found = {r["row_id"] for r in db.query(f"SELECT row_id FROM {table} WHERE row_id IN ({marks})", ids)}
        missing += [i for i in ids if i not in found]
    return missing


def _main(argv: list[str]) -> int:
    db = get_db()
    if argv[:1] == ["--check"]:
        n = int(argv[1]) if len(argv) > 1 else 5
        ids = [r["patient_id"] for r in db.query(
            "SELECT patient_id FROM curated.patients WHERE death_date IS NULL ORDER BY patient_id")]
        rng = random.Random(42)
        ok = True
        for pid in rng.sample(ids, min(n, len(ids))):
            facts = compute_facts(pid, db)
            kinds: dict[str, int] = {}
            for f in facts:
                kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
            no_src = [f for f in facts if not f["source_row_ids"]]
            missing = missing_row_ids(facts, db)
            ok = ok and not missing and not no_src
            print(f"{pid}  facts={len(facts):3d}  {kinds}  missing_rows={len(missing)}  no_sources={len(no_src)}")
        print("OK" if ok else "FAILED")
        return 0 if ok else 1
    if not argv:
        print(__doc__)
        return 2
    print(json.dumps(compute_facts(argv[0], db), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
