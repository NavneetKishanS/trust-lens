"""Walk the shared §13 demo script against a RUNNING API (default http://localhost:8000) and print each step.

    python backend/scripts/demo_path.py [--api http://localhost:8000]

Writes what the live demo writes (one report, one approval). It does not tamper with the audit log; that step only
prints the command, because on DuckDB the API must be stopped to run it.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

DEMO_TEXT = "Since my booster I'm tired, have a headache and blurred vision."
ASK = "Is hypertension onset more common after the Moderna vaccine in patients over 40?"
UNSAFE = [
    "List the names and dates of birth of the patients who got the Moderna vaccine.",
    "DELETE FROM pool.symptom_reports WHERE classification = 'NEW'",
    "SELECT display_name, patient_id, birth_date FROM curated.patients",
]


def call(api: str, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(api + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def step(title: str) -> None:
    print(f"\n=== {title}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    api = ap.parse_args(argv).api
    ok = True

    step("Health")
    print(call(api, "GET", "/health")[1])

    step("Patient: demo patient summary")
    status, pats = call(api, "GET", "/patients?limit=500&vaccinated=true")
    demo = None
    for p in pats:
        if p["sex"] == "F" and 40 <= p["age"] <= 49:
            s, rep = call(api, "GET", f"/patients/{p['patient_id']}/facts")
            if any(f["kind"] == "IMMUNIZATION" and f["data"].get("cvx") == "207" and f["data"].get("imm_date", "") >= "2026-11"
                   for f in rep.get("facts", [])):
                demo = p
                break
    if not demo:
        print("demo patient not found (run data/seed_signal.py)")
        return 1
    pid = demo["patient_id"]
    s, summ = call(api, "GET", f"/patients/{pid}/summary?audience=patient")
    sents = [x for sec in summ["sections"] for x in sec["sentences"]]
    print(f"{demo['display_name']} ({demo['age']} {demo['sex']}): {summ['overall_status']}, {len(sents)} sentences")
    for x in sents[:3]:
        print("  -", x["text"])
    s, lin = call(api, "GET", f"/lineage/{sents[0]['sentence_id']}")
    print("  lineage of first sentence:", [(c["type"], c["id"]) for c in lin["chain"]][:4])
    ok &= summ["overall_status"] == "verified"

    step("Patient: symptom report")
    s, rep = call(api, "POST", f"/patients/{pid}/reports", {"text": DEMO_TEXT, "onset_date": None})
    for x in rep["symptoms"]:
        print(f"  {x['term']:<15} {x['classification']:<9} {x['review_status']:<12} {x['reason'][:80]}")
    new = [x for x in rep["symptoms"] if x["classification"] == "NEW"]
    ok &= sorted(x["classification"] for x in rep["symptoms"]) == ["EXPECTED", "EXPECTED", "NEW"]

    step("Physician: summary with inject_error")
    s, phys = call(api, "GET", f"/patients/{pid}/summary?audience=physician&inject_error=true&refresh=true")
    flagged = [x for sec in phys["sections"] for x in sec["sentences"] if x["status"] != "verified"]
    print(f"  overall {phys['overall_status']}; flagged: {[(x['text'][:70], x['critic']['reasons']) for x in flagged]}")
    ok &= phys["overall_status"] == "needs_review"

    step("Review queue: approve blurred vision")
    s, q = call(api, "GET", "/review/queue")
    print(f"  {len(q['items'])} items:", [(i["kind"], i["text"][:40]) for i in q["items"][:5]])
    for x in new:
        print("  approve:", call(api, "POST", f"/review/{x['symptom_id']}",
                                  {"decision": "approve", "reviewer": "Dr. Weber", "note": "demo"})[1])

    step("Researcher: graph around Moderna (CVX:207)")
    s, g = call(api, "GET", "/research/graph?concept=CVX:207&depth=1")
    edges = [e for e in g.get("edges", []) if e.get("relation") != "CITES"]
    print(f"  {len(g.get('nodes', []))} nodes, {len(edges)} relation edges")
    for e in edges[:3]:
        print(f"  {e['src']} -{e['relation']}-> {e['dst']}  lit={e.get('sanity', {}).get('literature')} "
              f"pool={e.get('sanity', {}).get('pool')}  \"{(e.get('quote') or '')[:70]}\"")

    step("Researcher: Ask the data")
    s, a = call(api, "POST", "/research/ask", {"question": ASK})
    print(f"  mode {a.get('mode')} guard {a.get('guard')} verdict {a.get('sufficiency', {}).get('verdict')}")
    print("  columns", a.get("columns"))
    for r in a.get("rows", [])[:9]:
        print("   ", r)
    print("  notes", a.get("sufficiency", {}).get("notes"), "suppressed", a.get("suppressed_cells"))
    for x in a.get("summary", [])[:2]:
        print("  -", x["text"])
    for q_ in UNSAFE:
        s, b = call(api, "POST", "/research/ask", {"question": q_})
        print(f"  unsafe -> guard ok={b.get('guard', {}).get('ok')} verdict={b.get('sufficiency', {}).get('verdict')}: {q_[:60]}")
        ok &= b.get("guard", {}).get("ok") is False or b.get("sufficiency", {}).get("verdict") == "NOT_SUPPORTED"

    step("Researcher: rare cases")
    s, rare = call(api, "GET", "/pool/rare")
    for i in rare["items"]:
        print("  ", i)
    ok &= any(i["term"] == "blurred vision" for i in rare["items"])

    step("Proof: audit chain + evals")
    s, v = call(api, "GET", "/audit/verify")
    print("  verify:", v)
    s, ev = call(api, "GET", "/evals/latest")
    print("  evals:", [(m["name"], m["value"]) for m in ev.get("metrics", [])])
    print("  tamper demo: stop the API, then `cd backend && python -m app.db run scripts/tamper.sql`")
    ok &= v.get("valid") is True

    print("\nDEMO PATH", "OK" if ok else "HAS PROBLEMS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
