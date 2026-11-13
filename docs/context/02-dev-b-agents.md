# Dev B — Backend API, Trust Engine, Agents, Evals

> Read `00-shared.md` first. This file covers only your slice.

## 1. Mission

Own the FastAPI service that implements **every endpoint in shared §7**. That covers the trust engine
(plan → validate → verdict → approve → analyse), the physician/patient agent loop (generator → critic → verifier),
the hash-chained audit log, and the eval harness. Rules and SQL decide; the LLM explains, extracts and drafts.

## 2. You deliver (to Dev C)

| Deliverable | By | Notes |
|---|---|---|
| API skeleton returning **contract-shaped stubs** for all endpoints | H2 | Dev C switches off mocks one endpoint at a time |
| `GET /health`, audit append + verify | H3 | |
| Researcher flow on real checks (DuckDB) | H10 | Needs Dev A's `db.py` + `checks.sql`; stub until then |
| Physician summary + critic + verifier + review queue | H14 | |
| Patient overview, reports, community pool, voice | H16 | |
| Evals endpoint | H18 | |

## 3. Layout

```
backend/
  requirements.txt     # fastapi, uvicorn[standard], pydantic, anthropic, duckdb, pyexasol
  app/main.py          # FastAPI app, CORS for localhost:3000, routers
  app/db.py            # owned by Dev A (interface in 01-dev-a-data.md §5)
  app/models.py        # Pydantic models = exact shapes from shared §7
  app/llm.py           # Claude client factory + stub mode
  app/audit.py         # append(actor, action_type, subject, payload) -> seq ; verify()
  app/lineage.py       # add_edges(derived_id, derived_type, sources, transform, agent, model, prompt)
  app/research/        # planner.py, validate.py (runs db/checks.sql), verdict.py, analysis.py, report.py
  app/agents/          # generator.py, critic.py, verifier.py
  app/routes/          # research.py, patients.py, review.py, community.py, lineage.py, audit.py, evals.py
  app/evals.py
```
Run with `uvicorn app.main:app --reload --port 8000`. Python ≥ 3.10 (the Anthropic SDK 1.x needs it).

## 4. LLM client (`app/llm.py`)

- `LLM_PROVIDER=bedrock` → `from anthropic import AnthropicBedrockMantle`, `AnthropicBedrockMantle(aws_region="eu-central-1")`,
  model `"anthropic.claude-opus-5-5"`. Check early that this model is enabled in our AWS account and region.
- `LLM_PROVIDER=anthropic` → `anthropic.Anthropic()`, model `"claude-opus-5-5"`. Server-side refusal fallbacks are available here
  (`client.beta.messages...` with beta `server-side-fallback-2026-07-01`, `fallbacks="default"`); they aren't available on Bedrock.
- `LLM_PROVIDER=stub` (default when no credentials) → deterministic, template-based outputs so the demo can never die.
- Structured output: `client.messages.parse(model=..., max_tokens=..., messages=[...], output_format=<PydanticModel>)`.
- Opus 5.5 specifics: thinking is always on, so **don't** pass `thinking={"type":"disabled"}` (400). Control depth with
  `output_config={"effort": "low"|"medium"|"high"}`: use `low` for extraction, `medium` for summaries.
  No assistant prefill. Forced `tool_choice` returns a 400, so use structured outputs instead.
- **Always check `stop_reason`.** On `"refusal"` or any exception, return a result marked `needs_review`, and never return empty or OK.
- Record `model` and `sha256(prompt)` for every call, and pass them to `lineage.add_edges`.

## 5. Trust engine

1. **Planner** (`POST /research/runs`): Claude extracts `requirements` (shared §7 shape) from the question.
   Validate the result against known labs and LOINC codes; the stub uses keyword rules. Write to `validation.runs` and audit `run.created`.
2. **Validate**: read `db/checks.sql`, run each `-- name:` block (skip names starting with `_`), insert into
   `validation.check_results` with `run_id`, build `check_id = "CHK-{check_name}-{lab_id}"`, and audit `run.validated`.
3. **Verdict** (`verdict.py`): pure function following the shared §8 rules. Then Claude writes `explanation`, given **only**
   the check rows, and must cite `check_id`s. Post-check: every cited ID must exist; if not, fall back to the template text.
   Each WARN or FAIL check becomes one limitation `LIM-n`.
4. **Approve**: record accepted and rejected limitations and compute `permitted_analysis`. A rejected limitation drops its lab.
   A method-change limitation means stratify that lab by method. Audit `run.approved`.
5. **Analysis**: SQL on `curated.hba1c WHERE include_flag=1` plus permitted labs and stratification. Output monthly mean
   mmol/mol per series, per-patient first→last change (median), and excluded counts by reason. `report_markdown` lists the question,
   verdict, accepted limitations with evidence SQL, results, and lineage references. Audit `analysis.generated`.

## 6. Agent loop (physician)

- **Generator**: input is the patient's rows since `since` (default: the last encounter before the latest one) plus earlier history.
  Output `claims[]`, each with `text` and `citations` (row IDs that must come from the input). With `inject_error=true`, change one
  number in one claim (stub: always; LLM: post-edit deterministically) to set up the demo.
- **Critic** (deterministic, no LLM):
  1. every citation exists and belongs to this patient
  2. every number in `text` appears in a cited row (allow ±0.1 rounding, and allow % ↔ mmol/mol conversion)
  3. dates in `text` match cited row dates
  4. caveats: a cited result is affected by a WARN check (e.g. LAB_B after 2025-07-01, a LAB_C serum specimen) → add it to `caveats`
- **Verifier**: an entailment check that the cited rows support the claim. Use the Exasol in-SQL AI function if Dev A's probe finds one;
  otherwise Claude (`effort="low"`, structured `{status, reason}`); stub mode reruns the critic.
- **Routing**: critic FLAG or verifier ≠ SUPPORTED → `needs_review` and audit `claim.flagged`. Persist to `agents.claims`.
  `overall_status` is `needs_review` if any claim needs review.
- **Patient overview**: built from the *same* claims, rewritten in plain language (around a 12-year-old's reading level, no new facts, keep caveats).
  `next_steps`: next HbA1c due = last HbA1c + 90 days, and the follow-up from the latest encounter note. Each step cites a source.

## 7. Oversight, community, audit, evals

- Review queue = `agents.claims` where `review_status='needs_review'` plus `community.patient_reports` where `review_status='pending'`.
  A decision updates the row and audits `review.decision`.
- Community pool: **approved** reports only. Group by symptom and suppress counts under k=5 as `"<5"`. `rare` = in the bottom 10% by frequency.
- Audit: append computes `seq = max+1` and the hash per shared §9 under a process lock. Verify recomputes every row in order.
- Evals (`GET /evals/latest`): defect recall and precision from the latest run versus `evals.seeded_defects`. Claim support rate = claims
  with verifier SUPPORTED out of all claims over a 20-patient batch. Abstention correctness = the `inject_error` claim gets flagged
  10/10 times. Store results in `evals.runs`.

## 8. ElevenLabs (optional, after H16)

`POST https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}` with header `xi-api-key`, JSON `{"text": ..., "model_id": ...}`,
returning `audio/mpeg`. Check the current model ID in ElevenLabs' docs. Speak only the plain summary **including caveats**. With no key, return 501.

## 9. Definition of done

- [ ] Every shared §7 endpoint returns the exact shape (Pydantic models), both in stub mode and with a real LLM
- [ ] The researcher run on the seeded data returns `CONDITIONAL` with 9 limitations
- [ ] `inject_error` is always caught by the critic, and the claim appears in the review queue
- [ ] `/audit/verify` is valid; manually editing one row in the DB makes it invalid (show this in the demo)
- [ ] An LLM outage or refusal produces `needs_review`, never a crash or a silent OK
- [ ] Every LLM output has lineage edges with model and prompt hash

## 10. Pitfalls

- Don't let the LLM pick the verdict or invent row IDs. Validate everything it returns against the DB.
- Keep prompts in files (`app/prompts/*.md`) so the prompt hash is stable and reviewable.
- CORS: allow `http://localhost:3000`.
- Contract change? Edit shared §7 first and tell Dev C.
