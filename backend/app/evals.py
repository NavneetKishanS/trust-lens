"""Evals (M5): measure the trust claims against planted ground truth (shared §10) and store the numbers.

    POST /evals/run      runs every metric, stores one row per metric in evals.runs, audits eval.completed
    GET  /evals/latest   the latest run

Metrics (value is a rate in [0, 1], or None when it couldn't be measured; details say why):
  injected_error_catch_rate         PL1: a wrong number injected into a physician summary is flagged
  sentence_support_rate             share of summary sentences that pass the critic and the verifier
  symptom_classification_accuracy   PL3: the symptom engine's class vs the planted expected class
  unsafe_query_block_rate           PL4: unsafe Ask-the-data questions are blocked or fully suppressed
  fabricated_quote_rejected         PL5: the fabricated quote in the latest graph build was rejected by A2
  audit_chain_valid                 the hash chain recomputes

Summary metrics run the pipeline without persisting, so evals never add items to the review queue.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from . import audit
from .db import DB, get_db
from .schema import table_exists

PATIENT_SAMPLE = 10


def _sample_patients(db: DB, n: int) -> list[str]:
    """Deterministic sample of living patients with at least one lab value we have a range for."""
    labs = "SELECT loinc FROM ref.lab_ranges" if table_exists(db, "ref.lab_ranges") else "SELECT NULL AS loinc"
    rows = db.query(
        "SELECT DISTINCT p.patient_id FROM curated.patients p JOIN curated.observations o ON o.patient_id = p.patient_id "
        f"WHERE p.death_date IS NULL AND o.value_num IS NOT NULL AND o.concept_code IN ({labs}) "
        f"ORDER BY p.patient_id LIMIT {int(n)}")
    return [r["patient_id"] for r in rows]


def injected_error_catch_rate(db: DB, patients: list[str]) -> tuple[float | None, dict]:
    from .clinical import summary

    runs = []
    for pid in patients:
        r = summary.evaluate(pid, "physician", inject_error=True, db=db)
        if not r["injected"]:
            continue
        hit = next((s for s in r["sentences"] if s["text"] == r["injected"]["sentence"]), None)
        runs.append({"patient_id": pid, "changed": f"{r['injected']['from']} -> {r['injected']['to']}",
                     "caught": bool(hit and not hit["ok"]),
                     "critic_reasons": hit["critic"]["reasons"] if hit else []})
    if not runs:
        return None, {"note": "no patient with a lab sentence to inject into"}
    caught = sum(r["caught"] for r in runs)
    return caught / len(runs), {"caught": caught, "runs": len(runs), "per_patient": runs}


def sentence_support_rate(db: DB, patients: list[str]) -> tuple[float | None, dict]:
    from .clinical import summary

    total = ok = 0
    by_audience = {}
    flagged = []
    for audience in ("patient", "physician"):
        a_total = a_ok = 0
        for pid in patients:
            r = summary.evaluate(pid, audience, inject_error=False, db=db)
            for s in r["sentences"]:
                a_total += 1
                a_ok += s["ok"]
                if not s["ok"] and len(flagged) < 10:
                    flagged.append({"patient_id": pid, "audience": audience, "text": s["text"],
                                    "critic": s["critic"]["reasons"], "verifier": s["verifier"]["status"]})
        by_audience[audience] = {"sentences": a_total, "supported": a_ok}
        total, ok = total + a_total, ok + a_ok
    if not total:
        return None, {"note": "no sentences generated"}
    return ok / total, {"sentences": total, "supported": ok, "by_audience": by_audience, "examples_flagged": flagged}


def symptom_classification_accuracy(db: DB) -> tuple[float | None, dict]:
    if not table_exists(db, "evals.planted"):
        return None, {"note": "evals.planted missing; run data/seed_signal.py"}
    planted = db.query("SELECT item_id, description, expected FROM evals.planted WHERE kind = 'symptom_report'")
    if not planted:
        return None, {"note": "no planted symptom reports; run data/seed_signal.py"}
    got = {r["symptom_id"]: r["classification"] for r in db.query("SELECT symptom_id, classification FROM community.symptoms")}
    confusion: dict[str, int] = {}
    correct = 0
    for p in planted:
        sid = json.loads(p["description"]).get("symptom_id")
        actual = got.get(sid, "MISSING")
        correct += actual == p["expected"]
        key = f"{p['expected']}->{actual}"
        confusion[key] = confusion.get(key, 0) + 1
    return correct / len(planted), {"planted": len(planted), "correct": correct, "confusion": confusion}


def unsafe_query_block_rate(db: DB) -> tuple[float | None, dict]:
    if not table_exists(db, "evals.planted"):
        return None, {"note": "evals.planted missing; run data/seed_signal.py"}
    planted = db.query("SELECT item_id, description, expected FROM evals.planted WHERE kind = 'unsafe_query' ORDER BY item_id")
    if not planted:
        return None, {"note": "no planted unsafe questions; run data/seed_signal.py"}
    from .research import ask as ask_mod

    results = []
    for p in planted:
        want = json.loads(p["expected"])["outcome"]
        out = ask_mod.ask(p["description"], None, db=db)
        guard_ok = out["guard"]["ok"]
        numeric_small = any(c not in (None, "", "<5") and c.replace(".", "", 1).isdigit() and float(c) < 5
                            for row in out.get("rows", []) for col, c in zip(out.get("columns", []), row)
                            if col.startswith("n_") or col.startswith("count"))
        if want == "BLOCKED":
            passed = not guard_ok
        else:  # SUPPRESSED: may run, but no small count may leave as a number and the verdict can't be SUPPORTED
            passed = not numeric_small and out["sufficiency"]["verdict"] != "SUPPORTED"
        results.append({"item_id": p["item_id"], "expected": want, "passed": passed, "guard_ok": guard_ok,
                        "violations": out["guard"].get("violations", []), "verdict": out["sufficiency"]["verdict"],
                        "suppressed_cells": out.get("suppressed_cells")})
    return sum(r["passed"] for r in results) / len(results), {"questions": results}


def fabricated_quote_rejected(db: DB) -> tuple[float | None, dict]:
    builds = db.query("SELECT payload_json FROM gov.audit_events WHERE action_type = 'kg.built' ORDER BY seq DESC")
    for b in builds:
        payload = json.loads(b["payload_json"] or "{}")
        if payload.get("planted_pl5"):
            return (1.0 if payload.get("pl5_status") == "REJECTED" else 0.0), {
                "run_id": payload.get("run_id"), "edge_id": payload["planted_pl5"], "status": payload.get("pl5_status")}
    return None, {"note": "no graph build with a planted quote yet; POST /research/graph/build with "
                          "inject_fabricated_quote=true"}


def run(db: DB | None = None, patients: int = PATIENT_SAMPLE) -> dict:
    db = db or get_db()
    sample = _sample_patients(db, patients) if table_exists(db, "curated.patients") else []
    metrics: list[tuple[str, float | None, dict]] = []
    for name, fn in [("injected_error_catch_rate", lambda: injected_error_catch_rate(db, sample)),
                     ("sentence_support_rate", lambda: sentence_support_rate(db, sample)),
                     ("symptom_classification_accuracy", lambda: symptom_classification_accuracy(db)),
                     ("unsafe_query_block_rate", lambda: unsafe_query_block_rate(db)),
                     ("fabricated_quote_rejected", lambda: fabricated_quote_rejected(db))]:
        try:
            value, detail = fn()
        except Exception as exc:  # one broken metric must not hide the others
            value, detail = None, {"error": f"{type(exc).__name__}: {exc}"}
        metrics.append((name, value, detail))
    chain = audit.verify(db)
    metrics.append(("audit_chain_valid", 1.0 if chain["valid"] else 0.0, chain))

    eval_id = f"EVAL-{uuid.uuid4().hex[:12]}"
    created = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    db.insert_rows("evals.runs", [{"eval_id": eval_id, "metric_name": n, "metric_value": v,
                                   "detail_json": json.dumps(d, default=str), "created_at": created}
                                  for n, v, d in metrics])
    seq = audit.append("system:evals", "eval.completed", eval_id,
                       {"patients": len(sample), "metrics": {n: v for n, v, _ in metrics}}, db=db)
    return {**latest(db), "audit_seq": seq}


def latest(db: DB | None = None) -> dict:
    db = db or get_db()
    if not table_exists(db, "evals.runs"):
        return {"eval_id": None, "created_at": None, "metrics": [], "details": [{"note": "no eval run yet; POST /evals/run"}]}
    last = db.query("SELECT eval_id, created_at FROM evals.runs ORDER BY created_at DESC, eval_id DESC LIMIT 1")
    if not last:
        return {"eval_id": None, "created_at": None, "metrics": [], "details": [{"note": "no eval run yet; POST /evals/run"}]}
    rows = db.query("SELECT metric_name, metric_value, detail_json FROM evals.runs WHERE eval_id = ?", [last[0]["eval_id"]])
    order = ["injected_error_catch_rate", "sentence_support_rate", "symptom_classification_accuracy",
             "unsafe_query_block_rate", "fabricated_quote_rejected", "audit_chain_valid"]
    rows.sort(key=lambda r: order.index(r["metric_name"]) if r["metric_name"] in order else len(order))
    return {"eval_id": last[0]["eval_id"], "created_at": str(last[0]["created_at"]),
            "metrics": [{"name": r["metric_name"], "value": r["metric_value"]} for r in rows],
            "details": [{"name": r["metric_name"], **json.loads(r["detail_json"] or "{}")} for r in rows]}
