# Account Agent Memory Architecture

The V1 architecture is shifting from "signal-based workflow" to
**"account-as-agent"** — every account is its own intelligent object with
four distinct memory layers, and the orchestrator queries those agents
rather than reaching into raw sheets.

This doc explains what's shipped today vs what's queued for V1.5 / V2.

---

## The four memory layers

```
┌──────────────────────────────────────────────────────────────────────┐
│  AccountAgent  (apps/agent/src/account_agent.py)                     │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 1. PRESENT STATE MEMORY  (Current Snapshot Layer)              │  │
│  │    The live AccountNode — CRM fields, enrichment, usage,        │  │
│  │    intent signals, buying committee, active opps, last           │  │
│  │    activities, current health, ownership, contacts.              │  │
│  │    Used by: orchestrator, recommendation engine                 │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 2. HISTORICAL MEMORY    (Temporal State Layer)                 │  │
│  │    Field-level history. Signal evolution. Intent trend.          │  │
│  │    Champion changes. Adoption curve. Pipeline movement.          │  │
│  │    Previous AI scores + recommendations.                         │  │
│  │    Enables: journey reconstruction, trend analysis, forecasting │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 3. NARRATIVE MEMORY     (Account Story Layer)                  │  │
│  │    What the account does · strategic importance · pains today   │  │
│  │    · stakeholder relationships · CSM notes · AE strategy ·       │  │
│  │    objections · procurement blockers · expansion stories ·       │  │
│  │    risk indicators · key conversations · meeting summaries.      │  │
│  │    Reasoning context for AI; not just structured fields.        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 4. FEEDBACK MEMORY     (Learning Loop Layer)                   │  │
│  │    Every AI recommendation + which user received it + whether   │  │
│  │    they acted + outcome quality + positive/negative response.    │  │
│  │    Enables: RL behavior, personalized recommendations,           │  │
│  │    organizational learning, recommendation quality over time.   │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

## What's shipped (V1)

| Layer | V1 status | Where |
|---|---|---|
| **1. Present State** | ✅ full | `AccountAgent.present_state_summary()` wraps the existing `AccountNode`. |
| **2. Historical** | 🟡 hooks in place | `hydrate_agents_from_history()` reads `run_log/signals.csv` from every prior run and replays per-account snapshots into `agent.history`. Today's xlsx is static so trends are limited — they kick in the moment you do `make agent-run` a second time. |
| **3. Narrative** | 🟡 V1 lite | `bootstrap_narrative()` seeds from Gong business summary + Fireflies overview. New chunks can be added at runtime by the orchestrator (planned: signal narratives, CSM notes, feedback notes). |
| **4. Feedback** | 🟡 hooks in place | `hydrate_agents_with_feedback()` reads `run_log/outcomes.csv` (written by `/api/feedback`) and groups entries per account. Available to the orchestrator at the next run. |

## What V1.5 changes (the architectural follow-through)

| Layer | V1.5 plan |
|---|---|
| **1. Present State** | Materialized from Postgres `accounts` + `account_facts` (no behavioural change). |
| **2. Historical** | Replace CSV replay with a real `account_snapshots` table written per-run. Index by `(account_id, run_id)` for trend queries. Add field-level history (every CRM field change captured as an event). |
| **3. Narrative** | Move from "summaries on the node" to a real append-only `account_narratives` table. Add CSM notes / AE strategy via a `/api/account/{id}/note` endpoint. The reasoning agent's output is also written back so future runs see "what we said last time". |
| **4. Feedback** | Outcomes table with foreign keys to signals + users. Build a small ranker that adjusts `final_score` based on per-user / per-team feedback history. RL-flavored, not full RL. |

## The orchestrator's new contract

Today the LangGraph orchestrator does this:

```
load_accounts → filter → rank → assemble → reason → cap → persist
```

The architectural move is: **the orchestrator queries AccountAgents instead of raw nodes.**

```
agents = build_agents(nodes, run_log_dir)   # hydrates all 4 memory layers
        │
        ▼
filter / rank / assemble / reason / cap / persist all consume `agents[id]`
not `nodes[i]`.
```

Reasoning gets:
- the **Present State** (today's snapshot)
- the **Historical** summary (last 6 runs: how has score / band / health moved?)
- the **Narrative** chunks (the evolving story)
- the **Feedback** summary (what humans said about prior recommendations)

This is what makes the agent stop being a signal-generator and start being
an account-aware advisor.

## Implementation files

| File | Role |
|---|---|
| `apps/agent/src/account_agent.py` | AccountAgent class + memory dataclasses + hydration functions |
| `apps/agent/src/repository.py` | Builds the raw AccountNodes from xlsx (will read from Postgres in V1.5) |
| `apps/agent/src/persist.py` | Writes per-run snapshots + per-account contexts + outcomes |
| `apps/agent/schemas/signal.py` | Now carries `ontology_grounding` (backend taxonomy) + `business_logic` + 5 narrative `explanation_*` fields |
| `apps/agent/schemas/notification.py` | Now carries `investigate: InvestigateDetail` with factor-by-factor breakdown |
| `docs/gtm-ontology-canonical.pdf` | The canonical business brain that the agent grounds every claim in |
| `apps/agent/config/zuddl_ontology.py` | Distilled, token-efficient ontology appended to the LLM system prompt |

## The UX corollary — never expose taxonomy IDs

Internal IDs (`PAIN-003`, `EXP-001`, `P-003`, `Stage 3`, `Enterprise Expansion
Flywheel`) are how the **agent** thinks. They are **never** primary content
in the user-facing UI.

The UI rule:

| Layer | What surfaces |
|---|---|
| AE / CSM dashboards | Natural language only. "Why prioritized" · "Pain points detected" · "What changed recently" · "Why this matters strategically" |
| Signal detail page | The five narrative sections above, then drafts + evidence. The IDs live in a collapsible "🔧 Technical details" panel. |
| Investigate panel | "Why disqualified" + "What would change to re-qualify" + factor-by-factor breakdown (with positive / negative / neutral tags). No DQ#-codes in primary copy. |
| Executive dashboard | Aggregates with plain labels ("High priority" not "priority_band=high"). |
| Backend (signals.json, signals.csv, run_log/) | Keeps the IDs — they're useful for analytics, debugging, training. |

The principle: every recommendation must feel **explainable, human-readable,
strategic, actionable, context-aware**. The taxonomy is the backend's
language, not the user's.

## V2 — what real Account Agents look like

When the architecture is fully realized:

- Each account has a persistent agent (object) that survives across runs.
- That agent receives signals continuously, not in weekly batches.
- It maintains a running narrative ("VWO has been Yellow for 14 days; previous
  expansion ask received no response from Vipul; trying a different angle this
  cycle").
- The orchestrator becomes a coordinator across account agents, not the
  thinker. Each agent can reason about itself.
- Feedback memory drives per-user, per-team, per-segment personalization.

V1 ships the scaffolding (AccountAgent class, 4 memory accessors, hydration
plumbing). V1.5 ships durable storage + the real RL loop. V2 ships event-driven
agents.
