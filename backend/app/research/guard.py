"""SQL guard for "Ask the data" (Dev C §5 step 3). Runs before every execution, whatever produced the SQL.

Rules (any violation → blocked, nothing runs):
- exactly one statement, and it is a SELECT (WITH … SELECT and UNION of SELECTs are fine); no DML/DDL anywhere
- every table is a known pool.* view (or a CTE defined in the query); no table functions, no other schemas
- only whitelisted functions (aggregates, CAST, ROUND, CASE, string basics); unknown functions are blocked,
  which also stops things like getenv() or read_csv()
- no `*` except inside COUNT(*); `pseudo_id` may only appear in the output inside an aggregate
- the result must be aggregated (GROUP BY / aggregate), except reads of the pre-aggregated pool.rare_cases,
  and it must include a count column (n_… / COUNT) so small groups can be suppressed (k-anonymity)
- LIMIT 1000 is added (or lowered to 1000)
A question-level pre-check also refuses requests for identities, raw rows, writes or non-pool tables.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

MAX_ROWS = 1000
POOL_VIEWS = {"patients", "conditions", "observations", "medications", "immunizations", "symptom_reports",
              "rare_cases"}
PRE_AGGREGATED = {"rare_cases"}


def _types(*names: str) -> tuple[type, ...]:
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


ALLOWED_FUNCS = _types(
    "Count", "Sum", "Avg", "Min", "Max", "Median", "Stddev", "StddevPop", "StddevSamp", "Variance", "CountIf",
    "Round", "Cast", "TryCast", "Case", "If", "Coalesce", "Nullif", "Abs", "Ceil", "Floor", "Greatest", "Least",
    "Substring", "Lower", "Upper", "Trim", "Length", "Concat", "Extract", "Left", "Right")
FORBIDDEN_NODES = _types(
    "Insert", "Delete", "Update", "Drop", "Create", "Alter", "AlterTable", "Command", "Merge", "Into", "Copy",
    "Pragma", "Set", "Use", "Attach", "Detach", "Grant", "Revoke", "TruncateTable", "Transaction", "Commit",
    "Rollback", "Export", "LoadData")
OPERATORS = _types("Connector", "Binary", "Unary", "Predicate")  # AND/OR/LIKE/… are Func subclasses in sqlglot
_COUNT_NAME = re.compile(r"^(n|n_.+|count.*|.*_count)$", re.I)
_AGG_NAME = re.compile(r"(rate|pct|percent|share|ratio|avg|mean|median|proportion|min|max|sum|std)", re.I)

# --- question pre-check --------------------------------------------------------------------------
_IDENTITY = re.compile(
    r"\b(patients?'?s? names?|names? (of|for) (the |these |those |all )?(patients?|people|persons?)|their names?|"
    r"full names?|first ?names?|last ?names?|surnames?|birth ?dates?|dates? of birth|birthdays?|address(es)?|ssn|"
    r"social security|phone|e-?mail|uuids?|patient ids?|pseudo[_ ]?ids?|identif\w*|who (are|is) the patients?)\b",
    re.I)
_RAW_ROWS = re.compile(r"\b(raw rows?|all rows|every row|row[- ]level|individual (records?|patients?|rows?)|"
                       r"list (all|every|each) patients?|each patient'?s|export)\b", re.I)
_WRITE = re.compile(r"\b(delete|drop|truncate|insert|update|alter|grant|overwrite)\b", re.I)
_OTHER_SCHEMA = re.compile(r"\b(curated|gov|ref|clinical|community|research|raw|evals|information_schema|sys)\.\w+",
                           re.I)
SQL_START = re.compile(r"^\s*(select|with|delete|drop|insert|update|create|alter|truncate|merge|grant|call|copy|"
                       r"attach|pragma|set|export|import|execute)\b", re.I)


def check_question(question: str) -> list[str]:
    v = []
    if _IDENTITY.search(question):
        v.append("question asks for identifying data (names, IDs, birth dates, contact details); the pool has none")
    if _RAW_ROWS.search(question):
        v.append("question asks for row-level records; Ask the data only returns aggregates")
    if _WRITE.search(question):
        v.append("question asks to change data; Ask the data is read-only")
    if _OTHER_SCHEMA.search(question):
        v.append("question references a table outside pool.*")
    return v


# --- SQL guard -----------------------------------------------------------------------------------


@dataclass
class GuardResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    sql: str = ""  # rewritten SQL (LIMIT applied), only when ok
    tables: list[str] = field(default_factory=list)
    column_kinds: dict[str, str] = field(default_factory=dict)  # output column → count | aggregate | dimension


def _cte_map(tree: exp.Expression) -> dict[str, exp.Expression]:
    return {c.alias_or_name.lower(): c.this for c in tree.find_all(exp.CTE)}


def _selects(q: exp.Expression) -> list[exp.Select]:
    if isinstance(q, exp.Select):
        return [q]
    if isinstance(q, (exp.Union, exp.Intersect, exp.Except)):
        return _selects(q.left) + _selects(q.right)
    if isinstance(q, exp.Subquery):
        return _selects(q.this)
    return []


def _own_aggregate(sel: exp.Select) -> bool:
    if sel.args.get("group"):
        return True
    for proj in sel.expressions:
        for agg in proj.find_all(exp.AggFunc):
            if not agg.find_ancestor(exp.Window, exp.Subquery):
                return True
    return False


def _aggregated(q: exp.Expression, ctes: dict, depth=0) -> bool:
    if depth > 10:
        return False
    sels = _selects(q)
    if not sels:
        return False
    for sel in sels:
        if _own_aggregate(sel):
            continue
        sources = []
        from_ = sel.args.get("from_") or sel.args.get("from")
        if from_:
            sources.append(from_.this)
        sources += [j.this for j in sel.args.get("joins") or []]
        if not sources:
            return False
        for s in sources:
            if isinstance(s, exp.Table):
                name = s.name.lower()
                if not s.db and name in ctes:
                    if not _aggregated(ctes[name], ctes, depth + 1):
                        return False
                elif not (s.db.lower() == "pool" and name in PRE_AGGREGATED):
                    return False
            elif isinstance(s, exp.Subquery):
                if not _aggregated(s.this, ctes, depth + 1):
                    return False
            else:
                return False
    return True


def _unwrap(e: exp.Expression) -> exp.Expression:
    while isinstance(e, (exp.Alias, exp.Cast, exp.Paren)) or (isinstance(e, exp.Coalesce)):
        e = e.this
    return e


def classify(proj: exp.Expression) -> str:
    name = proj.alias_or_name or ""
    inner = _unwrap(proj)
    if _COUNT_NAME.match(name) or isinstance(inner, exp.Count):
        return "count"
    if proj.find(exp.AggFunc) or proj.find(exp.Div) or _AGG_NAME.search(name):
        return "aggregate"
    return "dimension"


def classify_name(name: str) -> str:
    if _COUNT_NAME.match(name or ""):
        return "count"
    return "aggregate" if _AGG_NAME.search(name or "") else "dimension"


def check_sql(sql: str, dialect: str = "duckdb") -> GuardResult:
    sql = (sql or "").strip()
    if not sql:
        return GuardResult(False, ["no SQL to run"])
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except sqlglot.errors.SqlglotError as e:
        return GuardResult(False, [f"SQL could not be parsed: {str(e).splitlines()[0][:200]}"])
    if len(statements) != 1:
        return GuardResult(False, [f"exactly one statement allowed, got {len(statements)}"])
    tree = statements[0]
    v: list[str] = []

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        v.append(f"only SELECT is allowed, got {tree.key.upper()}")
    for node in tree.walk():
        node = node[0] if isinstance(node, tuple) else node
        if FORBIDDEN_NODES and isinstance(node, FORBIDDEN_NODES):
            v.append(f"{node.key.upper()} is not allowed")
        elif isinstance(node, exp.Func) and not isinstance(node, ALLOWED_FUNCS + OPERATORS):
            fname = node.name if isinstance(node, exp.Anonymous) else node.sql_name()
            v.append(f"function {fname or node.key} is not allowed")

    ctes = _cte_map(tree)
    tables = set()
    for t in tree.find_all(exp.Table):
        name, schema = t.name.lower(), (t.db or "").lower()
        if not isinstance(t.this, exp.Identifier):
            v.append("table functions are not allowed")
        elif not schema and name in ctes:
            continue
        elif t.catalog or schema != "pool" or name not in POOL_VIEWS:
            v.append(f"table {t.sql(dialect=dialect)} is outside the anonymised pool (pool.*)")
        else:
            tables.add(f"pool.{name}")

    for star in tree.find_all(exp.Star):
        parent = star.parent.parent if isinstance(star.parent, exp.Column) else star.parent
        if not isinstance(parent, exp.Count):
            v.append("SELECT * is not allowed; name the columns")
            break

    outer = _selects(tree)
    kinds: dict[str, str] = {}
    for sel in outer[:1]:
        for proj in sel.expressions:
            kinds[proj.alias_or_name or proj.sql(dialect=dialect)] = classify(proj)
    for sel in outer:
        for proj in sel.expressions:
            for col in proj.find_all(exp.Column):
                if col.name.lower() == "pseudo_id" and not col.find_ancestor(exp.AggFunc):
                    v.append("pseudo_id may not be in the output unless aggregated (e.g. COUNT(DISTINCT pseudo_id))")
                    break

    if not v:
        if not _aggregated(tree, ctes):
            v.append("the result must be aggregated (GROUP BY / COUNT …); row-level output is not allowed")
        elif "count" not in kinds.values():
            v.append("add a count column (e.g. COUNT(DISTINCT pseudo_id) AS n_patients) so small groups can be suppressed")

    v = list(dict.fromkeys(v))
    if v:
        return GuardResult(False, v, tables=sorted(tables))

    limit = tree.args.get("limit")
    current = None
    if limit is not None:
        try:
            current = int(limit.expression.name if limit.expression is not None else limit.this.name)
        except (AttributeError, ValueError, TypeError):
            current = None
    if current is None or current > MAX_ROWS:
        tree = tree.limit(MAX_ROWS)
    return GuardResult(True, [], tree.sql(dialect=dialect), sorted(tables), kinds)
