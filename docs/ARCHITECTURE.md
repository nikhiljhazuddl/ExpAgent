# GTM Mesh — System Architecture

*A walkthrough you can present in 10 minutes. What the system is, why it's
shaped this way, and how a single click on a button ends up surfacing a real
expansion play.*

---

## 1 · The thesis in one paragraph

The GTM data layer at most B2B companies is rich — Salesforce, Gong,
Fireflies, Clay, product analytics, hiring feeds. The **action layer** is
broken. Signals sit in silos. CSMs and AEs rebuild context manually every
time. **GTM Mesh** is a Revenue Agentic System that fixes the action layer
with two architectural primitives that stay separate on purpose:

1. **Account Intelligence Nodes** — persistent per-account memory.
   The node *remembers*; it does not think.
2. **Use Case Agents** — orchestrator workflows with a specific revenue
   purpose. They *think*; they don't have to remember.

Build memory once, multiply across motions. **Expansion** is the first agent;
**Prospecting / Renewal / At-Risk** ship later against the same memory.

---

## 2 · The four layers (top-down view)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — DELIVERY                                                      │
│  Next.js web app + FastAPI service. Role-aware UI for AE / CSM / RevOps. │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 3 — USE CASE AGENT ORCHESTRATOR                                   │
│  LangGraph StateGraph. Filter → Rank → Assemble → Reason → Cap → Persist │
│  Reasoning fans out in parallel — one Claude/OpenAI call per candidate.  │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 2 — ACCOUNT INTELLIGENCE STORE                                    │
│  V1: in-memory AccountNode (join of 5 sheets) + filesystem persistence.  │
│  V1.5: same AccountNode shape, backed by Postgres + pgvector.            │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 1 — SIGNAL INGESTION                                              │
│  V1: pre-curated xlsx with 117 accounts. V2: live SF / Gong / Pylon /    │
│  Clay / product feeds.                                                    │
└──────────────────────────────────────────────────────────────────────────┘
```

The contract between layers is a strict Pydantic schema. Anything crossing a
layer boundary is type-checked. That's what lets us swap V1's filesystem
for V1.5's Postgres without touching the agent.

---

## 3 · The two architectural primitives, expanded

### 3.1 · Account Intelligence Node

> "The node *remembers*. It does not think."

For each customer account, the system assembles a single record (the
`AccountNode`) joining:

| Source | Carries |
|---|---|
| Salesforce *Account-Data* | AE name, AE role, CSM name, plan end date, open-opp flags, activity dates, health status, ~319 columns total |
| Salesforce *Expansion Data* | Use case gap (the trigger), adoption health, ACV, segment, target departments, usage rollups per event type |
| Gong + Fireflies | Call summaries, product interests mentioned, competitors mentioned, action items, topics |
| *Contacts_From_SF* | ~2,168 known users in product, with title, seniority, persona, persona-fit score |
| *Contacts Not in ProdSF* | ~877 Clay-found ICPs at customer accounts, tagged by event-type relevance |

**Why this is its own thing:** Once you have a per-account node, every future
agent (prospecting, renewal risk, at-risk recovery) just consumes the same
shape. Adding a new motion is a new orchestrator over existing memory, not
a re-integration.

### 3.2 · Use Case Agent — Expansion (V1)

The Expansion Agent is a deterministic-orchestrator + LLM-reasoning hybrid.

```
                          deterministic                  LLM-driven
                          ─────────────                  ──────────
   trigger detection ──► disqualifiers ──► ranking ──► reasoning ──► capping ──► delivery
   (Step 1)              (Step 2)          (Step 3)     (Step 4–5)     (Step 6)    (Step 6)
```

Steps 1–3 are cheap, audit-friendly Python. They run on every account in
seconds. They cut **117 → 44 candidates** without spending a token.

Step 4 (context assembly) builds a frozen 6,000-token input per candidate.

Step 5 (reasoning) is one LLM call per candidate, in parallel, schema-validated.
The agent confirms the gap is real, identifies a pain point, picks the best
persona, and writes the 5-section output the CSM/AE actions on.

Steps 6 caps each rep's queue to 5 signals/week and persists everything.

The full details — fields, formulas, thresholds, prompt — are in
[EXPANSION_AGENT.md](EXPANSION_AGENT.md). This doc is about the *shape*.

---

## 4 · LangGraph — why it's the orchestration spine

LangGraph gives us four properties out of the box that matter:

| Property | What it buys us |
|---|---|
| **Typed `StateGraph`** | Every node has the same shared `AgentState`. Type errors fail at compile time, not in prod. |
| **`Send` API** | Native parallel fan-out. We dispatch one LLM call per candidate with a single line — no manual asyncio. `max_concurrency=8`. |
| **Checkpointing** | A failed run resumes from the last successful node. V1 uses `MemorySaver`; V1.5 swaps that one line for `PostgresSaver` and gets durable resumability. |
| **Conditional edges** | `dry-run` mode skips the reasoning + cap nodes via a one-line edge function. Same graph, two modes. |

The flow:

```
                          ┌───────┐
                          │ START │
                          └───┬───┘
                              ▼
                  ┌──────────────────────┐
                  │   load_accounts      │ Repository → 117 AccountNodes
                  └──────────┬───────────┘ Data-quality log → CSV
                             ▼
                  ┌──────────────────────┐
                  │     filter_node      │ Step 1 trigger (104 pass)
                  │  Step 1 + Step 2     │ Step 2 DQ1..DQ5 (60 drop)
                  └────┬─────────────┬───┘ 44 survivors + 60 notifications
                       │             │
                       ▼             ▼
         ┌──────────────────────┐  ┌──────────────────────┐
         │ notify_disqualified  │  │      rank_node       │ priority_score
         │  (transparency log)  │  │  weighted composite  │ (no LLM)
         └────────────┬─────────┘  └──────────┬───────────┘
                      └────────┬──────────────┘
                               ▼
                    ┌──────────────────────┐
                    │    assemble_node     │ AccountContext per survivor
                    │   (6k-token cap)     │ Prune order if oversize
                    └──────────┬───────────┘
                               ▼
                       conditional edge
                       (dry_run ─► persist)
                               │
                               ▼
                    ┌──────────────────────┐
                    │   fan_out_router     │ One Send per ranked candidate
                    │  (LangGraph Send)    │
                    └──────────┬───────────┘
                               │ ×44 parallel
                               ▼
                    ┌──────────────────────┐
                    │     score_one        │ Single LLM call per candidate
                    │  Claude / OpenAI     │ JSON-mode output
                    │  Pydantic-validated  │ Retry-once-on-validation-error
                    └──────────┬───────────┘
                               │ Accumulator
                               ▼
                    ┌──────────────────────┐
                    │      cap_node        │ Top 5 per AE, top 5 per CSM
                    │                      │ Drop priority_band="low"
                    └──────────┬───────────┘
                               ▼
                    ┌──────────────────────┐
                    │    persist_node      │ run_log/* (audit + replay)
                    │                      │ output/*  (API contract)
                    └──────────┬───────────┘
                               ▼
                            ┌─────┐
                            │ END │
                            └─────┘
```

---

## 5 · Persistence: V1 (filesystem) → V1.5 (Postgres)

Two physical stores in V1, both flat files:

```
run_log/                          (audit + replay store)
  agent_runs.csv                   one row per run with funnel summary
  signals.csv                      one row per signal (kept + dropped),
                                   full JSON payload column
  notifications.csv                one row per disqualifier hit
  non_triggered.csv                accounts with no use-case gap
  data_quality.csv                 join misses, missing fields, drift
  outcomes.csv                     feedback from /api/feedback
  contexts/<id>.json               frozen AccountContext per scored
                                   account, raw AccountNode for the rest

output/                            (API contract — what the web reads)
  signals.json                     all kept signals (latest run)
  runs.json                        historical run summaries
  run_summary.json                 funnel + DQ breakdown + queue depth
  queues/by_ae/<slug>.json         capped queue per AE
  queues/by_csm/<slug>.json        capped queue per CSM
  notifications/by_ae/<slug>.json  transparency log per AE
  notifications/by_csm/<slug>.json transparency log per CSM
```

**V1 → V1.5 mapping** (the only two modules that change):

| V1 file/module | V1.5 destination |
|---|---|
| `repository.py` reads xlsx | `repository.py` runs SQL against `accounts`, `account_facts`, `contacts`, `gong_calls` |
| `persist.py` writes JSON/CSV | `persist.py` INSERTs into `agent_runs`, `signals`, `account_events`, `account_snapshots`, `outcomes` |
| `MemorySaver` checkpointer | `PostgresSaver` (one line in `graph/build.py`) |

**Nothing else changes:** filter logic, ranker, context builder, reasoning,
LangGraph nodes, prompts, schemas, FastAPI, web app. By design.

---

## 6 · API + Web — Layer 4

The FastAPI service is a thin passthrough over `output/*.json`:

| Endpoint | Purpose |
|---|---|
| `GET  /api/me` | Returns the current fake-login identity (role + user) |
| `GET  /api/users` | Auto-discovers AE/CSM list from the latest run output |
| `GET  /api/signals?role=&user=` | Filtered signal queue (RevOps gets all) |
| `GET  /api/signals/{id}` | One signal in full |
| `GET  /api/notifications?role=&user=` | Disqualification log |
| `GET  /api/accounts/{id}` | Read-only frozen account context |
| `GET  /api/runs` & `/api/runs/latest` | Run history + summary |
| `POST /api/feedback` | Writes to `run_log/outcomes.csv` |
| `POST /api/agent/run` & `/api/agent/run/dry` | Trigger a new agent run |

No auth in V1 — a cookie `session=role=AE&user=Bhargav%20Prasad` is the
"identity". Real auth lands in V1.5.

**The web app is a Next.js 14 App Router project**, mostly server
components. Six pages:

| Page | Audience | Renders |
|---|---|---|
| `/login` | Anyone | Role + person dropdown, sets cookie |
| `/dashboard` | AE/CSM | Top-5 capped signal cards |
| `/dashboard` | RevOps/Admin | Funnel + DQ breakdown + queue-depth tables + all signals |
| `/signal/[id]` | Anyone | Full signal: 5 sections + sticky metadata sidebar + Copy + feedback buttons |
| `/notifications` | AE/CSM see their own; RevOps sees all | Disqualification log with Investigate link |
| `/accounts/[id]` | Anyone | Read-only account context (for investigating dropped accounts) |
| `/runs` | RevOps/Admin only | Historical runs |

---

## 7 · The "one click on a card" flow (end-to-end)

```
1. User clicks "Sonar" card on /dashboard
   │
2. Browser navigates to /signal/20260518-134011:001J300000L4VdS
   │
3. Next.js server component (app/signal/[id]/page.tsx) executes
   │   - decodeURIComponent(params.id)
   │   - calls api.signal(id) helper
   │
4. Helper fetches GET /api/signals/<id> against the FastAPI service
   │
5. FastAPI route reads apps/agent/output/signals.json
   │   - finds the signal by id
   │   - returns the full Signal payload as JSON
   │
6. Server component receives the Signal, renders five sections
   │   1 · why_now
   │   2 · whats_missing
   │   3 · who_to_target (with buying role, source, LinkedIn)
   │   4 · supporting_context
   │   5 · draft_outreach (subject + body + Copy button)
   │
7. User clicks "Mark Relevant"
   │
8. Client POST /api/feedback {signal_id, relevant: true}
   │
9. FastAPI appends a row to run_log/outcomes.csv
```

That's it. No databases queried. The whole UI is reading flat files via a
typed JSON contract that won't change when V1.5 swaps to Postgres.

---

## 8 · How V1 became "agentic" without being magical

The system is **deterministic where it can be, LLM-driven where it must be**.

| Step | Deterministic? | Why this split |
|---|---|---|
| 1 — Trigger detection | Yes — pure boolean check | One column. No reasoning needed. |
| 2 — Disqualifiers | Yes — five rules over typed fields | Auditable. Same input → same output every run. |
| 3 — Ranking | Yes — weighted formula | Cheap, explainable, replayable. |
| 4 — Context assembly | Yes — schema-driven | The agent never sees raw rows; only validated context. |
| 5 — Reasoning + persona | **LLM** — schema-constrained | This is the actual judgment call. No structured rule beats "pick the right persona for this gap given this conversation history." |
| 6 — Capping + routing | Yes — sort + per-role top-N | Predictable load on every rep. |

Result: ~95% of the cost (in latency, money, attention) goes to step 5
where it earns its keep. The other 95% of decisions in the pipeline are
plain Python a reviewer can read and trust.

---

## 9 · Failure modes and how the system handles them

| Failure | Behavior |
|---|---|
| Account in Expansion Data missing from Account-Data | Account skipped + logged to `data_quality.csv`. Never silently dropped. |
| Missing CSM | Signal routes to AE only. `csm_missing=True` flag on the node. Notification surfaces this to RevOps. |
| LLM returns invalid JSON | Schema validation fails → one retry with the validation error appended to the prompt → final fallback returns `is_signal=false` with `reasoning_trace="validation_error: ..."`. The schema is the contract; never broken in `output/*.json`. |
| LLM rate-limited / 5xx | Tenacity exponential backoff (3 attempts, 1s → 20s). |
| Disqualified account but user wants to investigate | Raw `AccountNode` JSON is persisted for every triggered account, so `/accounts/{id}` works for the 60 disqualified ones too. |
| Run interrupted mid-flight | `MemorySaver` checkpointer resumes from the last completed node. V1.5 makes this durable across processes. |

---

## 10 · What V2 looks like (so we know what V1 is building toward)

| Component | V1 | V1.5 | V2 |
|---|---|---|---|
| Data | Static xlsx | Postgres + pgvector | Live SF / Gong / Pylon / Clay ETL |
| Memory | In-memory AccountNode | Persistent `accounts` + `account_facts` + `account_snapshots` tables | Same shape, real-time updated |
| Triggers | Schedule-only | Schedule + manual via UI | Event-driven (renewal date passes 120d, hiring signal lands, competitor mention) |
| Use Case Agents | Expansion only | Expansion + Renewal-Risk | + Prospecting + At-Risk + Win-back |
| Reasoning | Claude (or OpenAI for tests) | Claude with thinking-mode | Same — model upgrades drop in as `MODEL=` env change |
| Output | 5 sections + draft email | Same + auto-personalized variant set | + thread continuation (multi-touch sequences) |
| Feedback loop | Mark Relevant button | Outcomes feed scoring weights | Closed-loop: signal performance retrains the ranker weights |
| Auth | None | Workspace SSO | RBAC + per-territory scoping |

---

## 11 · Why this isn't just "Claude wrapping Salesforce"

Three things separate this from a prompt-engineering project:

1. **Memory is a first-class entity.** AccountNode persists across motions.
   Tomorrow's Renewal Agent reads the same shape as today's Expansion Agent.
2. **The orchestrator is deterministic.** The LLM only fires after 5 rules
   have eliminated the noise. That makes outputs cheap, predictable, and
   auditable.
3. **Every claim is grounded.** The reasoning agent must cite specific
   signals (Gong quote, hiring count, ICP fit) in its `supporting_context`.
   Hallucination shows up as missing citations, which the validator catches
   structurally.

The agent doesn't *replace* the rep. It does the assembly-line work — joining,
filtering, ranking, drafting — so the rep starts every Monday with five
high-confidence plays already on the desk.

---

*Companion: [EXPANSION_AGENT.md](EXPANSION_AGENT.md) — the field-level
mechanics of how scoring, persona selection, and output are built.*
