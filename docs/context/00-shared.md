# TrustLens — Shared Context (everyone reads this first)

> Single source of truth for the team and for every AI coding agent working on the repo.
> If you change a contract in here, tell the other two devs right away.

## 1. What we are building

**Challenge:** Exasol × Medical Valley EMN, Healthcare Hackathon Bayern, Erlangen, 12–14 Nov 2026.
"Would you trust an AI with your health?" The brief asks us to pick one user and one pain, connect data,
build one workflow, prove evidence and uncertainty, and show human oversight.

**One-liner:** *TrustLens checks whether the data can answer before the AI answers.*
Every output comes with a verdict, the source rows behind it, its limitations, and a human sign-off.

**Primary user:** a clinical researcher asking:
> "Can we analyse changes in HbA1c across patients from different laboratories?"

**Secondary views (same engine, thinner UI):**
- **Physician:** a "since last visit" summary for one patient. Every sentence is cited and checked by agents, and flagged sentences go to review.
- **Patient:** a plain-language overview, next steps, and a symptom diary. Diary entries enter the research pool only after clinician review.

**Not building (roadmap slide only):** literature knowledge graph, a live patient community, blockchain,
real EHR integration.

## 2. The trust story (what the jury must see)

1. **Evidence shown:** every number and sentence has a source drawer: raw row → transform → agent → model.
2. **Uncertainty flagged:** deterministic validation checks produce a verdict: `SUPPORTED`, `CONDITIONAL` or `NOT_SUPPORTED`.
3. **Human oversight:** a researcher approves limitations, a clinician approves flagged claims and patient reports.
4. **Tamper-evident:** each action is appended to a hash-chained audit log, and a "Verify chain" button recomputes it live.
5. **Measured:** seeded defects in the synthetic data give a live eval panel showing what fraction of defects were caught.
6. **Sovereign:** data and in-database AI stay in Exasol, and the LLM runs in an EU region (Bedrock eu-central-1).

## 3. Architecture

```
Frontend (Next.js)  ──REST/JSON──►  Backend (FastAPI)  ──►  Exasol Personal on AWS (DuckDB locally)
  researcher / physician /             trust engine            raw · curated · validation · lineage
  patient / review / audit / evals     agent loop               audit · community · agents · evals
                                       analysis · evals    ──►  Claude (Bedrock EU or Anthropic API; stub fallback)
                                       audit chain          ──►  ElevenLabs TTS (optional)
```

| Layer | Owner | Tech |
|---|---|---|
| Data, schema, validation SQL, lineage and audit tables | **Dev A** | Exasol Personal (AWS), pyexasol, DuckDB fallback, Python |
| API, trust engine, agents, analysis, evals | **Dev B** | FastAPI, Anthropic SDK (Bedrock Mantle client), Pydantic |
| UI, lineage drawer, review queue, charts, demo | **Dev C** | Next.js (App Router, TypeScript), Recharts |

## 4. Repo layout

```
trustlens/
  CLAUDE.md                 # agent entry point → points here
  docs/context/             # these files
  data/generate.py          # synthetic cohort + seeded defects (Dev A)
  data/out/*.csv            # generated, git-ignored
  db/schema.sql             # Dev A
  db/checks.sql             # validation checks, '-- name:' blocks (Dev A)
  backend/app/              # FastAPI (Dev B); backend/app/db.py owned by Dev A
  frontend/                 # Next.js (Dev C); frontend/mocks/*.json from §7
```

Branches: `data/*` (A), `api/*` (B), `ui/*` (C). Merge to `main` small and often, and keep `main` runnable.

## 5. Glossary

| Term | Meaning |
|---|---|
| **Run** | One research question going through plan → validate → approve → analyse. `run_id` like `RUN-20261113-143012-a1b2` |
| **Check** | One deterministic SQL validation rule evaluated per lab. Status `PASS`, `WARN` or `FAIL` |
| **Limitation** | A WARN or FAIL check turned into a sentence the researcher must accept or reject |
| **Verdict** | `SUPPORTED`, `CONDITIONAL` or `NOT_SUPPORTED`, decided by rules (§8). The LLM only explains it |
| **Claim** | One sentence produced by the generator agent, carrying a list of `citations` (source row IDs) |
| **Source row ID** | Raw primary key; the prefix shows the table: `R` lab result, `E` encounter, `RX` medication, `PR` patient report, `P` patient |
| **Lineage edge** | derived artefact → source row, plus transform, agent, model and prompt hash |
| **Seeded defect** | A data problem we injected on purpose; the ground truth for evals |

## 6. Data contract (tables Dev B and Dev C can rely on)

All names are fully qualified and lowercase. Columns never use SQL reserved words (`value`, `unit`, `action`, etc.).

- `raw.labs(lab_id, name, default_unit, default_method, loinc_code, accreditation)`
- `raw.patients(patient_id, display_name, sex, birth_year, diagnosis_code, diagnosis, home_lab_id, source_system)`
- `raw.lab_results(result_id, patient_id, lab_id, loinc_code, test_name, result_value, result_unit, lab_method, specimen, collected_at, source_file, source_row)`
- `raw.encounters(encounter_id, patient_id, encounter_date, encounter_type, clinician, note_text, source_file)`
- `raw.medications(rx_id, patient_id, drug, dose, start_date, end_date, prescriber, source_file)`
- `curated.hba1c(result_id, patient_id, lab_id, collected_at, collected_month, lab_method, specimen, loinc_code, raw_value, raw_unit, value_mmol_mol, value_pct, transform, is_duplicate, include_flag, exclusion_reason)`
- `validation.check_results(run_id, check_name, lab_id, check_status, metric, detail, mitigation, affected_rows, evidence_sql, created_at)`
- `validation.runs(run_id, question, requirements_json, verdict, explanation, approved_by, approved_at, created_at)`
- `lineage.edges(derived_id, derived_type, source_id, source_type, transform, agent, model, prompt_hash, created_at)`
- `audit.events(seq, event_ts, actor, action_type, subject, payload_json, prev_hash, row_hash)`
- `community.patient_reports(report_id, patient_id, symptom, severity, note_text, what_helped, reported_at, review_status, reviewed_by, reviewed_at)`
- `agents.claims(claim_id, summary_id, patient_id, claim_text, citations, critic_status, critic_reason, verifier_status, verifier_reason, review_status, reviewed_by, created_at)`
- `evals.seeded_defects(defect_id, defect_type, expected_check, lab_id, description)`
- `evals.runs(eval_id, metric_name, metric_value, detail, created_at)`

**HbA1c conversion:** `mmol/mol = 10.929 × % − 23.5` and `% = (mmol/mol + 23.5) / 10.929`. Store both values, rounded to 1 decimal.
**HbA1c LOINC codes:** `4548-4` (%), `59261-8` (IFCC mmol/mol), `17856-6` (% by HPLC). Anything else is the wrong test.

## 7. API contract (Dev B serves, Dev C consumes)

Base: `http://localhost:8000`. All JSON. Errors: `{"error": {"code": "...", "message": "..."}}`.
Dev C builds against `frontend/mocks/<endpoint>.json` with exactly these shapes until Dev B's endpoint is live.

### System
- `GET /health` → `{"status":"ok","db":"exasol|duckdb","llm":"bedrock|anthropic|stub"}`

### Researcher flow
- `POST /research/runs` body `{"question": str}` →
  ```json
  {"run_id":"RUN-...","question":"...","status":"planned",
   "requirements":{"population":"Adults with T2DM (E11.*)","test":{"name":"HbA1c","loinc_codes":["4548-4","59261-8","17856-6"]},
     "time_period":{"start":"2024-01-01","end":"2026-09-30"},"outcome":"Change in HbA1c over time",
     "comparison":"Across laboratories","labs":["LAB_A","LAB_B","LAB_C"]}}
  ```
- `POST /research/runs/{run_id}/validate` →
  ```json
  {"run_id":"RUN-...","status":"validated",
   "checks":[{"check_id":"CHK-unit_consistency-LAB_C","check_name":"unit_consistency","lab_id":"LAB_C",
     "status":"WARN","metric":1.0,"detail":"LAB_C reports %; others mmol/mol","mitigation":"Convert % → mmol/mol (IFCC formula)",
     "affected_rows":812,"evidence_sql":"SELECT ..."}],
   "verdict":{"level":"CONDITIONAL","explanation":"... cites [CHK-...] ...",
     "limitations":[{"limitation_id":"LIM-1","check_id":"CHK-unit_consistency-LAB_C","text":"...","mitigation":"...","requires_approval":true}]}}
  ```
- `POST /research/runs/{run_id}/approve` body `{"approved_by": str, "accepted": ["LIM-1"], "rejected": ["LIM-3"]}` →
  `{"run_id":"...","status":"approved","permitted_analysis":{"labs":["LAB_A","LAB_B","LAB_C"],"stratify_by_method":["LAB_B"],"exclusions":["duplicates","wrong_test_code","invalid_specimen","implausible"]},"audit_seq":17}`
  (Rejecting a limitation removes the affected scope from the analysis, e.g. that lab is dropped.)
- `GET /research/runs/{run_id}/analysis` →
  ```json
  {"run_id":"...","series":[{"series_id":"LAB_A","label":"LAB_A (HPLC)","points":[{"month":"2024-03","mean_mmol_mol":61.2,"n":14}]}],
   "patient_change":{"n_patients":231,"median_change_mmol_mol":-4.1,"by_lab":[{"lab_id":"LAB_A","n":80,"median_change_mmol_mol":-4.5}]},
   "excluded":[{"reason":"duplicate","rows":21}],"report_markdown":"# Evidence report ...","verdict":"CONDITIONAL"}
  ```

### Physician flow
- `GET /patients?limit=50` → `[{"patient_id":"P0001","display_name":"...","birth_year":1961,"home_lab_id":"LAB_A","last_visit":"2026-06-12"}]`
- `GET /patients/{id}/timeline` →
  `{"patient":{...},"events":[{"event_id":"R000123","type":"lab|encounter|medication|report","date":"2026-06-12","title":"HbA1c 58.0 mmol/mol","detail":"...","source":{"table":"raw.lab_results","row_id":"R000123","source_file":"lab_a_export_2026.hl7"},"flags":["method_changed"]}]}`
- `POST /patients/{id}/summary` body `{"since": "2026-06-01"|null, "inject_error": false}` →
  ```json
  {"summary_id":"SUM-...","patient_id":"P0001","since":"2026-06-12","overall_status":"needs_review",
   "claims":[{"claim_id":"CLM-...","text":"HbA1c fell from 64.1 to 58.0 mmol/mol since March.","citations":["R000120","R000123"],
     "critic":{"status":"PASS|FLAG","reasons":[]},"verifier":{"status":"SUPPORTED|UNSUPPORTED|UNSURE","reason":"..."},
     "caveats":["R000123 measured after LAB_B method change"],"review_status":"auto_ok|needs_review|approved|rejected"}]}
  ```
  `inject_error: true` makes the generator include one wrong number so the critic can catch it during the demo.

### Patient flow
- `GET /patients/{id}/overview` → `{"plain_summary":"...","next_steps":[{"text":"Next HbA1c test","due_date":"2026-09-10","source":"E000881"}],"caveats":["One result is missing ..."],"summary_id":"SUM-..."}`
- `POST /patients/{id}/reports` body `{"symptom","severity":1-5,"note_text","what_helped"}` → the report with `"review_status":"pending"`
- `POST /patients/{id}/voice` → `audio/mpeg` (returns 501 when no ElevenLabs key is set; the UI hides the button)

### Oversight
- `GET /review/queue` → `{"items":[{"item_id":"CLM-...","kind":"claim|patient_report","patient_id":"P0001","text":"...","reason":"critic: number mismatch","created_at":"..."}]}`
- `POST /review/{kind}/{item_id}` body `{"decision":"approve|reject","reviewer":str,"note":str}` → `{"ok":true,"audit_seq":42}`
- `GET /community/pool?diagnosis=E11.9` → `{"k":5,"n_reports":180,"symptoms":[{"symptom":"fatigue","count":"41","rare":false},{"symptom":"metallic taste","count":"<5","rare":true}],"what_helped":[{"text":"walking after meals","count":"23"}]}` (counts are strings because of `<5` suppression)
- `GET /lineage/{id}` → `{"id":"CLM-...","type":"claim","upstream":[{"id":"R000123","type":"raw.lab_results","transform":"normalize_hba1c","agent":"generator","model":"claude-opus-5-5","prompt_hash":"ab12...","created_at":"..."}]}`
- `GET /audit?limit=100` → `[{"seq":1,"event_ts":"...","actor":"...","action_type":"run.created","subject":"RUN-...","payload":{...},"prev_hash":"000...","row_hash":"9f2..."}]`
- `GET /audit/verify` → `{"valid":true,"length":57,"broken_at":null}`
- `GET /evals/latest` → `{"defect_recall":1.0,"defect_precision":0.9,"claim_support_rate":0.95,"abstention_correct":1.0,"details":[{"defect_id":"D01","expected_check":"unit_consistency","lab_id":"LAB_C","detected":true}]}`

## 8. Verdict rules (deterministic, the LLM never decides)

| Condition | Verdict |
|---|---|
| All checks PASS | `SUPPORTED` |
| Any WARN, or a FAIL that has a mitigation | `CONDITIONAL`, with one limitation per such check |
| Any FAIL without a mitigation in a lab the question needs, or fewer than 2 labs left after rejections | `NOT_SUPPORTED` |

Check thresholds are listed in `01-dev-a-data.md` §4. Claim routing: critic FLAG **or** verifier ≠ SUPPORTED → `needs_review`.
If the LLM returns a refusal or an error, the claim goes to `needs_review`. We never fail silently.

## 9. Audit hash chain

```
payload_canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
row_hash = sha256(prev_hash + "|" + event_ts_iso + "|" + actor + "|" + action_type + "|" + subject + "|" + payload_canonical)
genesis prev_hash = "0" * 64
```
Action types: `run.created`, `run.validated`, `run.approved`, `analysis.generated`, `summary.generated`,
`claim.flagged`, `review.decision`, `report.submitted`, `voice.generated`, `eval.completed`.

## 10. Seeded defects (ground truth, from data/generate.py)

| ID | Lab | Defect | Expected check |
|---|---|---|---|
| D01 | LAB_C | Reports in % while others use mmol/mol | `unit_consistency` |
| D02 | LAB_B | HPLC → immunoassay switch on 2025-07-01 | `method_comparability` |
| D03 | LAB_C | No results Jul–Sep 2025 | `time_coverage` |
| D04 | LAB_B | ~18% NULL values | `completeness` |
| D05 | LAB_A | ~4% rows coded as glucose (2345-7) | `test_consistency` |
| D06 | LAB_C | ~6% serum specimens | `specimen_consistency` |
| D07 | LAB_A | ~3% duplicate imports | `duplicates` |
| D08 | LAB_B | 4 values ×10 | `plausibility` |
| D09 | LAB_C | Only patients born before 1965 | `population_coverage` |

## 11. Environment variables

```
EXASOL_DSN=<host:8563>   EXASOL_USER=sys   EXASOL_PASSWORD=...   # unset → DuckDB at data/trustlens.duckdb
LLM_PROVIDER=bedrock|anthropic|stub   AWS_REGION=eu-central-1   ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...   ELEVENLABS_VOICE_ID=...
NEXT_PUBLIC_API_BASE=http://localhost:8000   NEXT_PUBLIC_USE_MOCKS=1
```
Never commit secrets. Use `.env` files, which are git-ignored.

## 12. Timeline (H = hours from kickoff)

| When | Milestone |
|---|---|
| H0–H2 | This file agreed. Exasol launching (A). API skeleton with stub responses (B). Mocks and page shells (C) |
| H2 | **Checkpoint 1:** `GET /health` works, data loaded into DuckDB, UI clicks through on mocks |
| H2–H10 | Parallel build |
| H10 | **Checkpoint 2:** researcher flow end to end on real checks (DuckDB OK) |
| H10–H16 | Physician and patient flows, review queue, audit verify, switch to Exasol |
| H16 | **Checkpoint 3:** feature freeze. Everything below is polish |
| H16–H20 | Evals panel, lineage drawer polish, failure-mode testing |
| H20–H24 | Rehearse the 3-minute demo ×3, record a backup video, slides |

## 13. Demo script (3 minutes)

1. **Hook (15s):** "Would you trust this?" Show a bare chatbot answer ("Everything looks normal").
2. **Researcher (75s):** ask the HbA1c question. Checks run, the verdict comes back `CONDITIONAL` with 9 limitations. Open one (LAB_B method switch) and its evidence SQL. Approve, and the stratified analysis plus report appear.
3. **Physician (45s):** open a patient summary with `inject_error` on. The critic flags the wrong number, the claim goes to the review queue, and the clinician rejects it.
4. **Patient (20s):** plain-language overview with "one result is missing, ask your doctor", optional voice readout, and a symptom report that lands as pending.
5. **Proof (25s):** eval panel shows 9/9 seeded defects caught; press Verify chain on the audit log; mention it all runs in Exasol in the EU.

## 14. Working agreements

- Contracts in §6–§9 change only by editing this file and telling the team.
- Mock first, integrate early. Never block on another dev; use the mock.
- Deterministic beats LLM wherever possible. The LLM explains, extracts and drafts; rules and SQL decide.
- No real patient data, ever. Only the synthetic data from `data/generate.py`.
- Every feature must answer: "How does this earn trust?" If it doesn't, cut it.
