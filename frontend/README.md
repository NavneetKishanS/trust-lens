# TrustLens UI (M4)

Next.js App Router + TypeScript + plain CSS. All data comes from the FastAPI service (shared §7); types live in `lib/types.ts`.

```bash
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev   # http://localhost:3000
```

| Route | Screen | API |
|---|---|---|
| `/` | Patient list | `GET /patients` |
| `/patient/[id]` | Patient summary, lineage drawer, symptom report | `GET /patients/{id}/summary?audience=patient`, `POST /patients/{id}/reports`, `GET /lineage/{id}` |
| `/physician/[id]` | Physician summary with codes, critic/verifier, `inject_error` toggle | `GET /patients/{id}/summary?audience=physician` |
| `/review` | Review queue, approve / reject | `GET /review/queue`, `POST /review/{item_id}` |
| `/research` | Ask the data, rare cases, knowledge graph edges | `/research/*`, `/pool/rare` |
| `/audit` | Audit log + Verify chain | `GET /audit`, `GET /audit/verify` |

Screens whose endpoints aren't live yet show "not available on the API yet" instead of failing.
Status is always colour + icon + text; AI text without sources is labelled "Unverified".
