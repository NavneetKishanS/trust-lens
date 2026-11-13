# Dev C — Frontend, Lineage UX, Demo

> Read `00-shared.md` first. This file covers only your slice.

## 1. Mission

Make trust **visible**. The jury judges in 3 minutes, so every screen must answer "where did this come from,
how sure are we, and who signed off?" You also own the demo script, the backup video and the slides.

## 2. You deliver

| Deliverable | By | Notes |
|---|---|---|
| Next.js app shell, routing, design tokens | H2 | |
| `frontend/mocks/*.json` for every shared §7 endpoint | H2 | Copy the shapes exactly; these become the contract tests |
| Researcher flow on mocks | H6 | The hero screen, so polish it first |
| Physician, patient, review queue on mocks | H10 | |
| Switch endpoints from mocks to the live API | H10–H16 | One by one as Dev B ships them |
| Audit, evals, lineage drawer | H16 | |
| Demo rehearsal, backup video, 5 slides | H20–H24 | Script in shared §13 |

## 3. Stack and setup

- Next.js (App Router, TypeScript) with Recharts for the trend chart. No heavy UI kit; plain CSS modules or Tailwind, your call.
- `lib/api.ts`: one typed function per endpoint. If `NEXT_PUBLIC_USE_MOCKS=1` it returns `mocks/<name>.json`, otherwise it fetches `NEXT_PUBLIC_API_BASE`.
  Types in `lib/types.ts` mirror shared §7 exactly.
- Run with `npm run dev` on port 3000.

## 4. Routes

| Route | Purpose |
|---|---|
| `/` | Role picker (Researcher · Physician · Patient · Clinician review) plus a one-line pitch |
| `/research` | Question box with an example pre-filled, then a stepper: **Understand → Validate → Verdict → Approve → Analyse** |
| `/research/[runId]` | Same view, deep-linkable for the demo |
| `/physician` | Patient list, then `/physician/[patientId]`: timeline on the left, cited summary on the right |
| `/patient/[patientId]` | Plain overview, next steps, caveats, symptom diary form, optional voice button |
| `/review` | Clinician queue (claims and patient reports) with approve and reject |
| `/community` | k-anonymised symptom pool (common vs rare) |
| `/audit` | Event list with hash chain and a **Verify chain** button |
| `/evals` | Seeded-defect recall, claim support rate, abstention, and a per-defect table |

## 5. Key components

- **VerdictBadge**: `SUPPORTED` green, `CONDITIONAL` orange, `NOT_SUPPORTED` red (matches the colleague's mock-up).
  Always show it with the explanation, never a badge alone.
- **CheckTable**: rows are check × lab with status chips. Expanding a row shows detail, mitigation, affected rows and `evidence_sql` in a code block.
- **LimitationList**: one card per `LIM-n` with Accept/Reject toggles. Approve sends `POST .../approve`. Disable approval until each limitation has a decision.
- **TrendChart**: one line per series (LAB_B split into "HPLC" and "Immunoassay" when stratified). Excluded-rows note under the chart.
- **ClaimCard**: claim text with **CitationChips** (row IDs). Shows a critic or verifier badge and caveats. A flagged claim gets a red border and a "Sent to clinician review" note.
- **CitationChip → LineageDrawer**: clicking any row or claim ID opens a side drawer. It calls `GET /lineage/{id}` and shows the chain:
  source file → raw row → transform → agent and model (with prompt hash) → claim. **This is the signature interaction; make it smooth.**
- **Timeline**: vertical list of events by date, typed icons (lab, encounter, medication, report), flags shown as small warning chips.
- **AuditChain**: rows show `seq`, time, actor, action, subject and a shortened hash linked to the previous hash. The Verify button shows a green "Chain valid (57 events)" or red "Broken at #23".
- **EvalPanel**: big numbers (e.g. "9/9 defects caught") with a per-defect table.

## 6. UX and copy rules (these earn trust)

- Never show an AI sentence without its sources. If there are no citations, show "Unverified" in grey.
- Say what's missing: "1 result missing", "LAB_C has no data Jul–Sep 2025".
- Patient view: no jargon, no diagnoses, no dosing advice. Always end with "Discuss this with your doctor." Show caveats in a calm amber callout, not red alarms.
- Show the human: "Approved by Dr. Weber at 14:32" wherever an approval happened.
- Mark AI-generated text with a small "AI draft · verified" or "AI draft · needs review" label.
- Loading states name the step ("Running 9 validation checks in Exasol…"). That's part of the story.
- Accessibility: colour plus icon plus text for every status (not colour alone), keyboard-reachable drawers, contrast AA.

## 7. Visual direction

Match the Exasol deck: dark teal background (`#062A38`-ish), cards a step lighter, accent green (`#5CC33F`-ish),
white text, generous spacing. Status colours: green, orange, red as in the colleague's mock-up. Define these as CSS variables in one file.

## 8. Demo ownership (shared §13)

- Build a hidden `/demo` page with buttons that seed state: reset DB, pre-filled question, patient with `inject_error`.
- Rehearse 3× with a timer. Record a backup screen video at H20 in case Wi-Fi or Exasol fails.
- 5 slides: problem (deck quote) → the trust gap → our flow (colleague's 6 steps) → live demo → impact and roadmap
  (knowledge graph, community, FDZ / EHDS secondary use, multi-site labs).

## 9. Definition of done

- [ ] Every route works on mocks **and** on the live API (toggle via env)
- [ ] Researcher flow completes in under 60s of demo time
- [ ] Lineage drawer works from every citation chip and from chart points
- [ ] Flagged claim shows up in `/review`, and approving it updates the physician view
- [ ] Verify chain button works; evals page shows real numbers
- [ ] Looks right at 1440px (projector) and doesn't break at phone width

## 10. Pitfalls

- Don't invent fields. If you need one, add it to shared §7 and tell Dev B.
- Community counts are strings (`"<5"`), so don't parse them as numbers.
- Keep mocks in sync with the contract; they double as Dev B's test fixtures.
