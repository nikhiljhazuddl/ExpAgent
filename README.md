# GTM Mesh — V1.5 (Production-bound)

> **You are in `gtm-mesh-prod`.** This is the production-bound copy that targets
> Supabase + Render + live integrations (Salesforce, Gong, Fireflies, Linear, Pylon).
>
> The V1 reference (static xlsx + local filesystem) lives at
> `~/Downloads/Zuddl-Mesh-IQ/` — keep it as the working baseline while V1.5 builds.

---

## What V1.5 changes (vs V1)

| Layer | V1 (local) | V1.5 (this codebase) |
|---|---|---|
| Storage | xlsx → in-memory + local JSON/CSV | **Supabase Postgres + pgvector** |
| Auth | cookie-based fake-login | **Supabase Auth** (with Zuddl SSO option) |
| Data sources | static xlsx + agent_brain.md | **Live**: Salesforce, Gong, Fireflies, Linear, Pylon |
| Sync orchestration | none — single dry-run | **Render Background Worker** + APScheduler |
| Agent runtime | local `make agent-run` | **Render Cron Job** (daily) |
| Deploy | localhost + Cloudflare quick tunnel | **Render** (web + API + workers) |
| Checkpointer | `MemorySaver` | `PostgresSaver` |

**Architecture detail:** see `docs/ACCOUNT_AGENT_MEMORY.md`. The orchestrator
(`apps/agent/src/graph/`), schemas, and prompts are unchanged from V1 — only
`repository.py` and `persist.py` swap to talk to Postgres.

## Build phases (this branch)

1. **Phase A — Postgres + repository/persist swap** (2–3 days)
2. **Phase B — Salesforce live sync** (5–7 days)
3. **Phase C — Gong live sync** (3–4 days)
4. **Phase D — Fireflies** (2–3 days)
5. **Phase E — Linear** (1–2 days)
6. **Phase F — Pylon** (2–3 days)
7. **Phase G — sync orchestration** (2 days)
8. **Phase H — Supabase Auth wiring** (1–2 days)
9. **Phase I — Render deploy** (1–2 days)
10. **Phase J — cutover** (2–3 days)

**MVP (Postgres + SF + Gong + auth) — Week 2. Full integrations — Week 5.**

## Setup

```bash
cp .env.example .env       # fill in Supabase service-role key + integration secrets
make install                # uv + pnpm
# Phase A scaffold lands here:
#   apps/agent/migrations/*  (Alembic)
#   apps/agent/src/repository.py  (Postgres reads)
#   apps/agent/src/persist.py     (Postgres UPSERT)
#   apps/sync/                    (new — Render Background Worker)
```

See `docs/V1.5_MIGRATION_PLAN.md` (to be written in Phase A) for the canonical
schema + sync architecture.
# ExpAgent
# ExpAgent
