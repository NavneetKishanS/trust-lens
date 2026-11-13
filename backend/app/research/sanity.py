"""A3 Sanity checker (Dev C §4). Deterministic; it labels edges and never deletes them.

Literature: other ACCEPTED edges (from other papers) for the same concept pair.
  same direction → support, opposite (positive vs NO_ASSOCIATION_WITH, increases vs decreases) → contradict.
  lit_status = CONTESTED if contradict > 0, CONSISTENT if support > 0, else SINGLE_SOURCE.
Pool: if the pair is exposure (CVX / RxNorm) + condition (SNOMED) and both exist in our anonymised pool, run the
  exposure_outcome_rate SQL → OBSERVED (exposed rate > baseline and n ≥ 20), NOT_OBSERVED, or UNTESTABLE.
"""
from __future__ import annotations

from pathlib import Path

from app.research import deps, store
from app.research.concepts import CLASS_MEMBERS, ConceptIndex

POSITIVE = {"ASSOCIATED_WITH", "INCREASES_RISK_OF", "DECREASES_RISK_OF", "ADVERSE_EVENT_OF", "TREATS"}
MIN_N = 20
K = 5
WINDOW_DAYS = 90
SYNTHETIC_NOTE = "Synthetic pool (Synthea + planted signal PL2). Not a finding about real patients or vaccines."
FALLBACK_SQL = Path(__file__).parent / "sql" / "exposure_outcome_rate.sql"


def contradicts(a: str, b: str) -> bool:
    if (a == "NO_ASSOCIATION_WITH") != (b == "NO_ASSOCIATION_WITH"):
        return True
    return {a, b} == {"INCREASES_RISK_OF", "DECREASES_RISK_OF"}


def literature(edges: list[dict], paper_years: dict[str, int | None]) -> dict[str, dict]:
    """edges: accepted edges (edge_id, src_id, dst_id, relation, paper_id). Returns edge_id → literature label."""
    by_pair: dict[frozenset, list[dict]] = {}
    for e in edges:
        by_pair.setdefault(frozenset((e["src_id"], e["dst_id"])), []).append(e)
    out = {}
    for e in edges:
        support, contra = set(), set()
        for o in by_pair[frozenset((e["src_id"], e["dst_id"]))]:
            if o["paper_id"] == e["paper_id"]:
                continue
            (contra if contradicts(e["relation"], o["relation"]) else support).add(o["paper_id"])
        years = sorted(y for y in (paper_years.get(p) for p in support | {e["paper_id"]}) if y)
        status = "CONTESTED" if contra else "CONSISTENT" if support else "SINGLE_SOURCE"
        out[e["edge_id"]] = dict(lit_status=status, support_count=len(support), contradict_count=len(contra),
                                 support_years=dict(oldest=years[0], newest=years[-1]) if years else None)
    return out


def _exposure_sql(db) -> tuple[str, str]:
    """Dev A's named block if it exists anywhere in db/*.sql, else our fallback."""
    for path in sorted((deps.REPO_ROOT / "db").glob("*.sql")):
        blocks = deps.parse_named_blocks(path.read_text())
        if "exposure_outcome_rate" in blocks:
            return blocks["exposure_outcome_rate"], f"db/{path.name}:exposure_outcome_rate"
    return deps.parse_named_blocks(FALLBACK_SQL.read_text())["exposure_outcome_rate"], \
        "research/sql/exposure_outcome_rate.sql:exposure_outcome_rate"


def _kanon(n: int | None) -> str | None:
    if n is None:
        return None
    return "<5" if n < K else str(int(n))


def pool_available(db) -> bool:
    return all(deps.table_exists(db, t) for t in ("pool.patients", "pool.immunizations", "pool.conditions"))


def pool_check(src: str, dst: str, index: ConceptIndex, db=None) -> tuple[str, dict | None]:
    db = db or deps.get_db()
    cs = [index.get(src), index.get(dst)]
    exposure = next((c for c in cs if c and c.is_exposure), None)
    outcome = next((c for c in cs if c and c.code_system == "SNOMED"), None)
    if not exposure or not outcome:
        return "UNTESTABLE", dict(reason="pair is not an exposure (CVX/RxNorm) and a condition (SNOMED)")
    if not pool_available(db):
        return "UNTESTABLE", dict(reason="anonymised pool not available")
    present = db.query("SELECT COUNT(*) AS n FROM pool.conditions WHERE concept_code = ?", [outcome.code])[0]["n"]
    if not present:
        return "UNTESTABLE", dict(reason=f"{outcome.label} is not in the pool", outcome=outcome.concept_id)
    sql, source = _exposure_sql(db)
    params = dict(exposure_code=exposure.code, outcome_code=outcome.code, window_days=WINDOW_DAYS)
    codes = [m.split(":", 1)[1] for m in CLASS_MEMBERS.get(exposure.concept_id, [exposure.concept_id])]
    if len(codes) > 1:  # class concept: count any member (codes come from our own list, never from user input)
        if "concept_code = :exposure_code" not in sql:
            return "UNTESTABLE", dict(reason="pool SQL cannot test a vaccine class", sql_source=source)
        sql = sql.replace("concept_code = :exposure_code", f"concept_code IN ({', '.join(repr(c) for c in codes)})")
        params.pop("exposure_code")
    try:
        row = deps.query_named(db, sql, params)[0]
    except Exception as e:  # noqa: BLE001 - a failed check is UNTESTABLE, never a crash
        return "UNTESTABLE", dict(reason=f"pool query failed: {type(e).__name__}", sql_source=source)
    n_exp, n_out_exp = int(row["n_exposed"] or 0), int(row["n_outcome_exposed"] or 0)
    n_unexp, n_out_unexp = int(row["n_unexposed"] or 0), int(row["n_outcome_unexposed"] or 0)
    exp_rate = 100.0 * n_out_exp / n_exp if n_exp else None
    base_rate = 100.0 * n_out_unexp / n_unexp if n_unexp else None
    evidence = dict(
        sql=sql, sql_source=source, sql_hash=store.sha256(sql)[:16], params=params,
        exposure=exposure.concept_id, exposure_codes=codes, outcome=outcome.concept_id,
        n_exposed=_kanon(n_exp), n_outcome_exposed=_kanon(n_out_exp),
        n_unexposed=_kanon(n_unexp), n_outcome_unexposed=_kanon(n_out_unexp),
        # rates computed from a suppressed count are blanked (k-anonymity)
        exposed_rate=None if exp_rate is None or n_out_exp < K else f"{exp_rate:.1f}",
        baseline_rate=None if base_rate is None or n_out_unexp < K else f"{base_rate:.1f}",
        synthetic=True, note=SYNTHETIC_NOTE)
    if n_exp < MIN_N or n_unexp < MIN_N:
        evidence["reason"] = f"fewer than {MIN_N} patients in a group"
        return "UNTESTABLE", evidence
    status = "OBSERVED" if exp_rate is not None and base_rate is not None and exp_rate > base_rate else "NOT_OBSERVED"
    return status, evidence
