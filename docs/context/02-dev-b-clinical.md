# Dev B — Backend Core and Clinical Agents (Patient + Physician)

> Read `00-shared.md` first (v2). This file covers only your slice. Milestone tags: **[M0]**, **[M1]**…

## 1. Mission

Own the FastAPI service core that everyone builds on (LLM client, audit chain, lineage), and the clinical engine:
evidence-backed summaries for patients and physicians, the symptom intake loop, and the review queue.
Rule of the slice: **SQL computes the facts, the LLM only phrases them, the critic proves it.**

## 2. Deliverables

| Milestone | Deliverable | By | Unblocks |
|---|---|---|---|
| M0 | FastAPI skeleton: every shared §7 route returning contract-shaped **stub** JSON | H1 | C, Swagger demo |
| M0 | `llm.py` (bedrock / anthropic / stub) + `gov.llm_calls` logging | H2 | C |
| M0 | `audit.py` (append, verify) + `lineage.py` (add, chain) + `/audit`, `/audit/verify`, `/lineage/{id}` live | H2 | everyone |
| M1 | Summary pipeline: facts → generator → critic → verifier, both audiences, `inject_error` | H6 | demo core |
| M2 | Symptom intake: extract → map → classify → store → queue | H8 | A's PL3 seeding |
| M2 | Review queue + decisions (sentences and symptoms); approve updates pool | H9 | C's rare cases |
| M5 | `/evals/latest`: injected-error catch rate, sentence support rate, symptom classification accuracy on PL3, guard block rate on PL4 | H16 | demo |

## 3. Layout

```
backend/
  requirements.txt      # fastapi, uvicorn[standard], pydantic, anthropic, duckdb, pyexasol, sqlglot
  app/main.py           # app, CORS (localhost:3000), routers
  app/models.py         # Pydantic models = exact shared §7 shapes (C reuses them)
  app/llm.py  app/audit.py  app/lineage.py
  app/clinical/facts.py      # runs db/facts.sql, stores clinical.facts
  app/clinical/generator.py  app/clinical/critic.py  app/clinical/verifier.py  app/clinical/summary.py
  app/clinical/symptoms.py   app/clinical/review.py
  app/prompts/summary_patient.md  summary_physician.md  verifier.md  symptom_extract.md
  app/routes/system.py clinical.py review.py governance.py
```
Run: `uvicorn app.main:app --reload --port 8000`. Python ≥ 3.10.

## 4. Core libs **[M0]**

**`llm.py`**
- `LLM_PROVIDER=bedrock` → `from anthropic import AnthropicBedrockMantle`; `AnthropicBedrockMantle(aws_region="eu-central-1")`, model `"anthropic.claude-opus-5-5"`. Confirm early that the model is enabled in our AWS account and region (mentor resources).
- `LLM_PROVIDER=anthropic` → `anthropic.Anthropic()`, model `"claude-opus-5-5"`.
- `LLM_PROVIDER=stub` (default) → deterministic template output. **The whole demo must work in stub mode.**
- One function: `call(purpose, prompt_file, variables, output_model) -> (parsed | None, meta)`. Uses `client.messages.parse(..., output_format=output_model)`.
  Opus 5.5: thinking is always on, so never pass `thinking={"type":"disabled"}`; set depth with `output_config={"effort": "low"|"medium"}`. No assistant prefill, no forced `tool_choice`.
- Check `stop_reason`; on `"refusal"`, an exception or a parse failure return `None` with `meta.ok=False`. Callers turn that into `needs_review`, never into an OK.
- `meta = {model, prompt_hash (sha256 of the prompt file), input_hash, stop_reason, latency_ms, ok}` → insert into `gov.llm_calls`.

**`audit.py`**: `append(actor, action_type, subject, payload) -> seq` under a process lock, hash per shared §9. `verify() -> {valid, length, broken_at}` recomputes every row in order.
**`lineage.py`**: `add(derived_id, derived_type, sources: list[(id, type)], transform, agent=None, model=None, prompt_hash=None)`; `chain(id, max_depth=4)` walks upstream for `/lineage/{id}`.

## 5. Summary pipeline **[M1]**

1. **Facts**: run every block of Dev A's `db/facts.sql` for the patient, store in `clinical.facts` with `FCT-` IDs, lineage fact → source rows (transform `facts.sql:<block>`). Until A ships it (H4), hand-write 2 blocks yourself (`lab_trend`, `encounter`).
2. **Select** by audience: patient = all kinds except `condition`; physician = all.
3. **Generator** (LLM, effort `medium`): input = facts JSON (fact_id + data) and the section list for the audience (shared §7). Output model:
   `{sections:[{title, sentences:[{text, fact_ids}]}]}`. Prompt rules: use only the given facts; copy numbers and dates exactly; patient = plain words at about a 12-year-old's reading level, `plain_name` instead of lab names, no diagnoses or advice (shared §8a); physician = concise, include codes (LOINC/SNOMED/RxNorm/CVX), no recommendations.
   **Stub:** one template sentence per fact.
4. **`inject_error=true`** (PL1): after generation, deterministically change one number in the first lab sentence (e.g. +17). Record it in the audit payload.
5. **Critic** (deterministic, `critic.py`), per sentence, returns `{status, reasons}`:
   - every `fact_id` exists and belongs to this patient
   - every number in the text appears in a cited fact (±0.1; allow the same value with or without unit)
   - every date or month in the text matches a cited fact date (accept `2025-03-11`, `March 2025`, `03/2025`)
   - no banned phrase for the audience (shared §8a)
   - patient audience: no word from a medical term list unless it appears in a cited fact (stops invented diagnoses)
6. **Verifier** (LLM, effort `low`, `prompts/verifier.md`): "Do these facts fully support this sentence? `{status: SUPPORTED|UNSUPPORTED|UNSURE, reason}`". Batch all sentences in one call. Stub: SUPPORTED if critic PASS.
7. **Route**: critic FLAG or verifier ≠ SUPPORTED → `needs_review`, audit `sentence.flagged`. Patient view shows the placeholder text (`hidden_pending_review`); physician view shows it with a flag.
8. **Persist** `clinical.summaries` + `clinical.sentences`; lineage sentence → facts (agent `generator`, model, prompt_hash); audit `summary.generated`.
9. Cache per `(patient, audience)` for the demo; `?refresh=true` regenerates.

## 6. Symptom intake **[M2]** (`POST /patients/{id}/reports`)

1. Store `community.reports`, audit `report.submitted`.
2. **Extract** (LLM, effort `low`, `prompts/symptom_extract.md`): `{symptoms:[{span, term}]}` where `span` must be an exact substring of the text (check it; drop items that aren't). Stub: keyword match against `ref.symptom_vocab` synonyms.
3. **Map** each term to `ref.symptom_vocab` (exact or synonym match, lowercase). No match → `UNMAPPED`.
4. **Classify** per shared §8, deterministic:
   - `EXPECTED`: patient has an immunization/medication whose code is in `ref.known_effects` with this term, and `onset_date` (or today) is within `window_days` of it. Evidence: the known-effect row + the IMM/MED row.
   - `IN_RECORD`: a condition or observation in the last 365 days whose description contains the term or a synonym. Evidence: that row.
   - else `NEW`. `NEW` and `UNMAPPED` → `review_status='pending'`, audit `symptom.flagged`.
5. Persist `community.symptoms`; lineage symptom → report (+ evidence rows).

## 7. Review queue **[M2]**

- `GET /review/queue` = sentences with `review_status='needs_review'` + symptoms with `review_status='pending'`, newest first, with reason and evidence.
- `POST /review/{item_id}`: set `review_status` to `approved|rejected`, `reviewed_by`, `reviewed_at`; audit `review.decision` with the note.
  Approved NEW symptom → appears in `pool.symptom_reports` and `pool.rare_cases` (Dev A's views do this automatically).
  Approved sentence → `verified` in later summary reads.

## 8. Definition of done

- [ ] `/docs` lists every shared §7 route; stub mode returns valid shapes for all of them
- [ ] Summary for 5 random patients, both audiences, every sentence has `fact_ids` that resolve via `/lineage` to OBS/ENC/… rows
- [ ] `inject_error=true` is flagged by the critic 10/10 times
- [ ] Patient summaries contain no banned phrase (run the critic over 20 patients)
- [ ] "tired, headache and blurred vision" after a CVX 207 dose → 2 EXPECTED, 1 NEW (pending); approving it shows it in `/pool/rare`
- [ ] LLM down or refusing → `needs_review`, never a 500 or a silent OK
- [ ] `/audit/verify` is valid; editing one row by hand makes it invalid

## 9. Pitfalls

- Never let the LLM create fact IDs, numbers or dates; the critic must catch anything it adds.
- Keep prompts in files so `prompt_hash` is stable. Changing a prompt is fine; it just changes the hash.
- Don't call the LLM per sentence for verification; batch it, or the summary takes too long for the demo.
