# GTM Mesh — Expansion Agent V1 Build Spec (Final)

**Owner:** Satyadeep Karnati · **Status:** Build-ready · **Version:** 2.0 (final)
**Build target:** Claude Code, local development, monorepo
**Stack:** Python 3.11, **LangGraph**, Claude API, FastAPI, Next.js 14 (App Router), Tailwind, shadcn/ui
**Persistence:** V1 = filesystem (JSON + CSV) → V1.5 = Postgres + pgvector (forward-compatible)
**Data source:** `data/Expansion_Agent_1.xlsx` (117 customer accounts, static)
**Authoritative inputs:** GTM_Mesh_PRD_BRD_v1, RevOps_GTM_Roadmap_1, Zuddl_ABM_Scoring_Framework, Agent Brain audio

This is the **single file** to paste into Claude Code along with the four source documents and the xlsx. The exact attach + run order is at the bottom (§16).

---

## 1. Architectural recap (one screen)

### The thesis

The GTM data layer is rich; the **action** and **orchestration** layers are broken. Signals sit in silos. CSMs and AEs rebuild context manually every time. GTM Mesh fixes this with two architectural primitives that stay separate on purpose:

1. **Account Intelligence Nodes** — persistent per-account memory. The node *remembers*; it does not think.
2. **Use Case Agents** — orchestrator workflows with a specific revenue purpose. Stateless between runs. Query the nodes, fan out reasoning, deliver ranked signals.

Build memory once, multiply across motions. Adding Prospecting / Renewal / At-Risk later is a new workflow over the same memory.

### Layered model

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 4 — DELIVERY (V1)                                            │
│  FastAPI service exposes JSON; Next.js renders role-based views     │
│  Roles: AE · CSM · RevOps · Admin (auth deferred to V1.5)           │
├────────────────────────────────────────────────────────────────────┤
│  LAYER 3 — USE CASE AGENT ORCHESTRATOR  (LangGraph StateGraph)      │
│  Nodes: filter → rank → assemble → reason (fan-out) → cap → persist │
│  Reason node uses LangGraph Send API for parallel fan-out           │
├────────────────────────────────────────────────────────────────────┤
│  LAYER 2 — ACCOUNT INTELLIGENCE STORE                               │
│  V1: in-memory AccountNode = join of 5 sheets                       │
│  V1.5: Postgres + pgvector with the 6-table PRD schema              │
├────────────────────────────────────────────────────────────────────┤
│  LAYER 1 — SIGNAL INGESTION                                         │
│  V1: pre-curated sheets (this work)                                 │
│  V2: live Salesforce / Gong / Fireflies / Pylon / product feeds     │
└────────────────────────────────────────────────────────────────────┘
```

### Why LangGraph

- Native parallel fan-out via `Send` — exactly the "group of reasoning agents controlled by an orchestrator" pattern.
- Typed `StateGraph` makes the 6-step flow auditable and testable.
- Built-in checkpointing means a failed run resumes; the same checkpointer is what V1.5 swaps for Postgres.
- LangGraph Studio gives visual run debugging out of the box — useful when you onboard the first CSM.

---

## 2. The expansion agent flow (LangGraph)

```
                   ┌─────────────┐
                   │   START     │
                   └──────┬──────┘
                          ▼
                  ┌───────────────┐
                  │ load_accounts │  loads 5 sheets, builds AccountNodes
                  └──────┬────────┘
                         ▼
                 ┌───────────────┐
                 │   filter_node │  Step 1 (trigger) + Step 2 (DQ1–DQ5)
                 └──────┬────────┘
              ┌─────────┴──────────┐
              ▼                    ▼
     ┌──────────────┐    ┌────────────────────┐
     │  rank_node   │    │ notify_disqualified │ writes transparency log
     └──────┬───────┘    └────────────────────┘
            ▼
    ┌────────────────┐
    │ assemble_node  │  builds AccountContext per candidate
    └──────┬─────────┘
           ▼
    ┌────────────────┐    LangGraph Send API → fan-out, max_concurrency=8
    │ reasoning_node │ ── one Claude call per candidate
    └──────┬─────────┘    each returns a Signal (kept or dropped)
           ▼
    ┌────────────────┐
    │   cap_node     │  Apply per-AE and per-CSM caps (3–5/wk)
    └──────┬─────────┘
           ▼
    ┌────────────────┐
    │ persist_node   │  writes run_log/* and the JSON the API serves
    └──────┬─────────┘
           ▼
         ┌─────┐
         │ END │
         └─────┘
```

Every node is a pure function over the shared `AgentState` TypedDict. Each transition is checkpointed; a `--replay <run_id>` restarts from any node using the saved checkpoint.

### AgentState

```python
class AgentState(TypedDict):
    run_id: str
    triggered_at: datetime
    config: RunConfig                     # caps, concurrency, dry_run flag
    all_accounts: list[AccountNode]       # loaded once
    triggered: list[AccountNode]          # Step 1 output
    disqualified: list[Notification]      # Step 2 transparency log
    survivors: list[AccountNode]          # Step 2 keepers
    ranked: list[RankedCandidate]         # Step 3 output
    contexts: dict[str, AccountContext]   # Step 4a output (account_id → context)
    signals: Annotated[list[Signal], operator.add]  # Step 4b (accumulated via Send)
    capped_by_role: dict[str, list[Signal]]  # Step 5 output: per-AE + per-CSM queues
    metrics: RunMetrics                   # tokens, cost, latencies
```

---

## 3. The six-step flow — exact rules

### Step 1 — Trigger detection

**Input:** all 117 rows of `Expansion Data`.
**Rule:** account triggers if `Use case gap (Prod data and usecase 2025)` (col K) is non-empty.
**Validation:** cross-check against Prod usage columns L–R; if column K names a use case the account *is* using, log to `data_quality.csv` but still trigger.
**Side effect:** write `run_log/non_triggered.csv` for the 13 accounts that don't trigger.
**Measured pass rate:** 104 of 117.

### Step 2 — Disqualifiers (5 rules)

Account is dropped if **any** is true. Each drop produces a `Notification` for the AE *and* the CSM (transparency contract — both roles see why an account they own was filtered out).

| # | Rule | Source | Definition |
|---|------|---|---|
| DQ1 | Red adoption | `Expansion Data!S` `Adoption Health from Prod` | value = `Red` (case-insensitive) |
| DQ2 | Recent activity | `Account-Data!AG` `Last Activity` | `today - last_activity < 30 days` |
| DQ3 | Named open opp | hardcoded list (§3.1) | account name in list of 10 |
| DQ4 | Open expansion opp flag | `Account-Data` col 196 `Has Open Expansion Opp?` | value > 0 |
| DQ5 | Inactive customer | `Account-Data` col 207 `Is Active Customer` (=0) OR col 205 `Inactive > 90 days?` (>0) | either true |

**Measured drop counts (on 104 triggered):** DQ1=27 · DQ2=23 · DQ3=6 · DQ4=2 · DQ5=2 → **44 survivors.**

#### 3.1 Hardcoded "open expansion opp" list (V1)

`config/open_expansion_opps.py` — case-insensitive trimmed match on Account Name.

```
T. Rowe Price · CrowdStrike · Fullscript · Under Armour · Figma
Turnitin · BigCommerce · Iterable · Tricentis · Postman
```

### Step 3 — Deterministic ranking

Cheap, audit-friendly, runs before any LLM call.

```
priority_score = 0.40 * adoption_score
               + 0.30 * renewal_proximity_score
               + 0.30 * usage_strength
```

| Component | Source | Mapping |
|---|---|---|
| adoption_score | `Expansion Data!S` | Green=1.0 · Yellow=0.6 · Red=0.2 |
| renewal_proximity_score | `Account-Data` col 255 `Plan End Date` (fallback col 218 `Latest Expansion Contract End`) | ≤120d=1.0 · 121–180d=0.6 · 181–365d=0.3 · >365d=0.1 · missing=0.4 |
| usage_strength | sum of `*_all_time` (Expansion Data L–R), then `log1p(total) / log1p(max_total)` across survivors | continuous 0–1 |

### Step 4 — Context assembly + parallel reasoning

`assemble_node` builds an `AccountContext` per ranked survivor (schema §5).

`reasoning_node` uses LangGraph `Send` to fan out — one Claude call per context — with `max_concurrency=8`. Each call is a pure function `(context, prompt, schema) → Signal`. Idempotent, replayable.

The reasoning agent does five things, in order:
1. **Confirms the gap is real** — cross-checks column K vs actual usage and Gong/Fireflies signals. If invalid, returns `is_signal=false` with reason.
2. **Identifies the pain point** — tied to evidence (a Gong quote, a hiring signal, a competitor mention).
3. **Picks the target persona** — compares `Contacts_From_SF` (existing product users) vs `Contacts Not in ProdSF` (Clay-found ICPs). Selection rules in §6.
4. **Writes the five-section CSM/AE-facing output** — *Why now · What's missing · Who to target · Supporting context · Draft outreach.*
5. **Sets `recommended_action_owner`** — `CSM` for adoption-led plays (gap surfaced by usage + existing-contact persona), `AE` for buyer-led plays (gap surfaced by new ICP discovery + Clay-found persona), or `BOTH` for high-confidence plays where both should engage. This is the routing intelligence, not just metadata.

### Step 5 — Cap and route (per AE + per CSM)

Every signal has two owners: **AE** (`Account-Data!C` Account Owner) and **CSM** (`Account-Data!DV` CSM owner). Both get the same signal in their queue.

**Capping rule (V1, explicit):**
- Each AE: top 5 signals/week by `final_score`.
- Each CSM: top 5 signals/week by `final_score`.
- An account fires into both queues independently. If AE's queue is full but CSM's isn't, the signal still appears in the CSM queue.
- Floor: signals with `priority_band = low` are never delivered, even if the queue has room.

**Measured routing matrix** (10 unique AE×CSM pairs across 44 survivors):

| AE | CSM | Accounts |
|---|---|---|
| Bhargav Prasad | Janhvi Gupta | 13 |
| Brooks Marsi | Janhvi Gupta | 8 |
| Brooks Marsi | Aastha Jindal | 5 |
| Bhargav Prasad | Aastha Jindal | 4 |
| Bhargav Prasad | Joe Huisman | 4 |
| Brooks Marsi | Saumitra Shekhar | 3 |
| Mark Whalen | Aastha Jindal | 2 |
| Mark Whalen | Janhvi Gupta | 2 |
| Mark Whalen | Saumitra Shekhar | 2 |
| Paul Singh | Saumitra Shekhar | 1 |

**Final score:**
```
final_score = 0.5 * LLM_confidence + 0.5 * priority_score
priority_band: high ≥ 0.70 · medium 0.45–0.69 · low < 0.45
```

### Step 6 — Persist + deliver

V1 writes everything to file under a forward-compatible structure (§8). The FastAPI service in `apps/api/` serves these files as JSON for the frontend. No DB yet.

---

## 4. Dual-ownership model (AE + CSM)

This is the most important conceptual change from V1.0 of the spec. Read carefully.

| Concept | V1 implementation |
|---|---|
| AE (Account Owner) | `Account-Data!C` (e.g., Bhargav Prasad) — pre- and post-sale relationship |
| AE Role | `Account-Data!AL` `Owner Role` (e.g., "AE (Americas)", "AE (APAC)") |
| CSM | `Account-Data!DV` `CSM owner` (e.g., Janhvi Gupta) — post-sale adoption + expansion |
| Routing principle | **Signals route to BOTH.** Each role has its own queue. Either can mark the signal actioned. |
| Conflict resolution | If AE actions first, CSM sees a "completed by AE" banner and vice versa. Stored in the outcomes log. |
| Cap accounting | Per-role, independent. An account counts against AE's cap *and* CSM's cap. |
| `recommended_action_owner` | The reasoning agent's opinion on who should drive — `AE`, `CSM`, or `BOTH`. Used as a visual signal in the queue, not a hard route. |

**Data quality reality:** all 44 survivors have both an AE and a CSM populated. 14 accounts in the broader Account-Data have no CSM (irrelevant for V1 since they didn't survive), but the repository must handle the missing-CSM case gracefully (route to AE only, flag the gap).

---

## 5. AccountContext schema (input to Claude)

Built per candidate. Capped to ~6,000 input tokens. Prune order if oversize: transcripts → contact lists → signal arrays.

```python
{
  "account_id": "0015i00000OrA0z",
  "account_name": "Zenoti",
  "domain": "zenoti.com",
  "ownership": {
    "ae": {"name": "Bhargav Prasad", "role": "AE (APAC)"},
    "csm": {"name": "Janhvi Gupta"}
  },
  "segment": "Enterprise",
  "acv_usd": 32000,

  "current_state": {
    "adoption_health": "Yellow",
    "active_use_cases_in_prod": ["Flagship","Webinars","Third-Party Events"],
    "use_case_gap_field": "Webinar; Third-Party Events",
    "renewal_proximity_days": 89,
    "is_active_customer": true,
    "has_open_expansion_opp": false,
    "last_activity_days_ago": 47
  },

  "usage": {
    "field_events_all_time": 0,
    "third_party_events_all_time": 0,
    "webinars_all_time": 0,
    "standard_in_person": 4,
    "standard_hybrid": 0,
    "standard_virtual": 1,
    "total_events_all_time": 5
  },

  "account_profile": {
    "target_departments": ["Operations","Marketing","Payments"],
    "sales_model": "Sales-led",
    "target_customers": ["Salon","Spa","Medspa","Fitness center","Barbershop"]
  },

  "signals_1p": { "factors_intent_label": "Warm", "demo_pricing_visits_90d": 3,
                  "factors_last_intent_date": "2025-12-17" },
  "signals_2p": { "linkedin_engagement_30d": 2, "zuddl_mentions": false,
                  "champion_job_moves_90d": 0 },
  "signals_3p": { "event_role_hiring_90d": 1, "competitor_mentions_g2_90d": 0,
                  "competitor_in_stack": ["Bizzabo"] },

  "icp_population": {
    "conferences_icp_count": 1, "field_events_icp_count": 0,
    "webinar_icp_count": 1,    "third_party_icp_count": 0
  },

  "conversations": {
    "has_gong": true, "has_fireflies": true, "total_calls": 12,
    "date_range": "2025-08-01 to 2026-04-22",
    "gong_business_summary": "...",
    "gong_product_interests": ["webinars","field marketing"],
    "gong_competitors_mentioned": ["Bizzabo","Hopin"],
    "gong_key_points": ["..."],
    "fireflies_overview": "...",
    "fireflies_action_items": ["..."],
    "fireflies_topics": ["pricing","integrations","field events"]
  },

  "contacts_in_product_sf": [
    {"name":"Sarah Chen","title":"VP Marketing","seniority":"VP",
     "persona":"Marketing Leader","persona_fit_score":92,"linkedin":"..."}
  ],
  "contacts_not_in_product_clay": [
    {"name":"Priya Rao","title":"Director of Field Marketing",
     "linkedin":"...","tagged_use_case":"Field Events","found_in_prod":false}
  ],

  "deterministic_priority_score": 0.71
}
```

---

## 6. Reasoning system prompt

`prompts/expansion_reasoning.py` — verbatim string, version-controlled.

```text
You are the Expansion Reasoning Agent for Zuddl's GTM Mesh, evaluating ONE customer
account at a time for a high-confidence expansion opportunity.

Your job is to produce a structured signal that EITHER the AE or the CSM (both will see it)
can action this week.

INPUTS
- An account_context object with current state, usage, signals, conversations,
  and two contact pools (existing SF contacts, Clay-found contacts not yet in product).
- The account's AE and CSM, both of whom will receive your output.
- A deterministic priority_score the orchestrator already computed.

DECISION RULES (apply in order)

1. CONFIRM THE GAP IS REAL.
   The "use_case_gap_field" is the system's best guess. Validate by checking:
   - The corresponding usage column in account_context.usage is 0 or near-zero.
   - Conversation data does not contradict it (they may have run a field event via workaround).
   - 1P/2P/3P signals lean toward NEED for that use case (intent visits, role hiring,
     competitor in stack).
   If the gap is NOT confirmed, return is_signal=false with a one-line reason.

2. IDENTIFY THE PAIN POINT.
   Tie the gap to a concrete pain or initiative grounded in evidence (a Gong quote,
   a hiring signal, a funding event, a competitor mention). Generic statements are
   not acceptable.

3. CHOOSE THE TARGET PERSONA.
   Compare contacts_in_product_sf and contacts_not_in_product_clay. Select ONE primary
   (you may name one secondary). Criteria, in order:
   a) Title relevance to the gap (Field Events → "Head of Events", "Field Marketing
      Manager", "Demand Gen Lead"; Webinars → "Marketing Ops", "Demand Gen", "Content
      Marketing Lead"; Third-Party → "Field Marketing Manager", "Event Marketing").
   b) Seniority sufficient to influence a buying decision.
   c) Buying role: Economic Buyer > Champion > Influencer > User.
   d) Tiebreaker: prefer existing SF contact (warmer entry, already a user) UNLESS
      Clay contact is clearly a better persona fit — then prefer Clay and note they
      are not yet in product.

4. RECOMMEND THE ACTION OWNER.
   - CSM if the play is adoption-led (existing user persona, gap surfaced by usage,
     renewal proximity drives urgency).
   - AE if the play is buyer-led (Clay-found new persona, new initiative based on
     hiring/intent, no existing relationship needed inside the account).
   - BOTH if both routes are strong (high confidence + multiple personas).

5. WRITE THE FIVE-SECTION OUTPUT (schema below).
   - why_now: 2–3 sentences. Concrete, time-bound, evidence-anchored.
   - whats_missing: the gap, in business terms the AE/CSM can repeat to the customer.
   - who_to_target: named persona, title, buying role, source (sf | clay), one-line
     "why this person".
   - supporting_context: 3–6 bullets each referencing a specific signal or quote.
     This is the audit trail.
   - draft_outreach: full email — subject + 3–5 short paragraphs + signoff. No
     hallucinated facts.

6. SCORE CONFIDENCE.
   0..1. High (>0.75) requires: confirmed gap + named persona with strong fit +
   ≥2 corroborating signals from different categories (e.g., one conversation cue
   + one 3P signal).

OUTPUT
Return ONLY valid JSON matching the schema you are given. No prose, no markdown.
```

---

## 7. Output schemas (Pydantic, JSON-mode enforced)

### Signal

```json
{
  "account_id": "string",
  "account_name": "string",
  "is_signal": true,
  "missing_use_case": "Webinar | Field Events | Third-Party Events | Conferences",
  "confidence": 0.84,
  "priority_band": "high | medium | low",
  "recommended_action_owner": "AE | CSM | BOTH",
  "ownership": {
    "ae": {"name": "Bhargav Prasad", "role": "AE (APAC)"},
    "csm": {"name": "Janhvi Gupta"}
  },
  "why_now": "string, 2–3 sentences",
  "whats_missing": "string, 1–2 sentences in business terms",
  "who_to_target": {
    "primary": {
      "name": "string", "title": "string",
      "buying_role": "economic_buyer | champion | influencer | user",
      "source": "sf | clay",
      "linkedin": "string|null",
      "why_this_person": "string, 1 sentence"
    },
    "secondary": null
  },
  "supporting_context": ["bullet 1","bullet 2","bullet 3"],
  "draft_outreach": { "subject": "string", "body": "string" },
  "reasoning_trace": "string, step-by-step inference",
  "model_metadata": { "model": "...", "tokens_in": 0, "tokens_out": 0, "latency_ms": 0 }
}
```

When `is_signal=false`: only `account_id`, `account_name`, `is_signal`, `reasoning_trace` required.

### Notification (transparency log)

```json
{
  "account_id": "string", "account_name": "string",
  "ae": "string", "csm": "string",
  "detected_gap": "string",
  "disqualifier_rule": "DQ1_red_adoption | DQ2_recent_activity | DQ3_named_open_opp | DQ4_open_opp_flag | DQ5_inactive",
  "explanation": "1 sentence, plain English",
  "want_more_info": true
}
```

---

## 8. Persistence model (V1 files → V1.5 Postgres)

```
run_log/
  agent_runs.csv          # one row per run
  signals.csv             # one row per signal (kept or dropped), JSON payload column
  notifications.csv       # one row per disqualified-but-detected account
  non_triggered.csv       # one row per account that did not trigger
  contexts/<account_id>.json   # frozen AccountContext per scored account
  outcomes.csv            # filled by feedback API
  data_quality.csv        # join misses, missing fields, ambiguous values

output/                   # served as JSON by FastAPI; also viewable directly
  signals.json            # all kept signals (latest run)
  queues/
    by_ae/<ae_slug>.json
    by_csm/<csm_slug>.json
  notifications/
    by_ae/<ae_slug>.json
    by_csm/<csm_slug>.json
  run_summary.json
```

**V1 → V1.5 table mapping:**

| V1 file | V1.5 Postgres table |
|---|---|
| `agent_runs.csv` | `agent_runs` |
| `signals.csv` (kept) | `signals` + `account_events`(`event_type=signal_generated`) |
| `signals.csv` (dropped) | `account_events`(`event_type=evaluation_no_signal`) |
| `notifications.csv` | `account_events`(`event_type=disqualified`) |
| `contexts/<id>.json` | `account_snapshots` |
| `outcomes.csv` | `outcomes` |

The repository in V1 mirrors what V1.5's repository layer will look like. **The LangGraph nodes do not change in V1.5** — only `repository.py` and `persist.py` swap.

---

## 9. Frontend — V1 scope

A working web app with **role-based views** and **no auth wired**. Users pick their role + identity from a dropdown (acts as a fake login). Wire real auth in V1.5.

### Roles (data model lives in V1 even though auth is off)

| Role | Sees |
|---|---|
| AE | Only signals where they are the AE. Both queue + notifications. |
| CSM | Only signals where they are the CSM. Both queue + notifications. |
| RevOps | All signals across all reps, all notifications, all run metrics. |
| Admin | Everything + user/role management (just a stub in V1). |

### Pages

1. **`/login`** — fake login: dropdown of (role, name). On select, sets a cookie `role=<role>&user=<name>`. No password.
2. **`/dashboard`** — role-aware landing.
   - AE/CSM: top 5 signals as cards, in priority order. Each card shows priority band, missing use case, why now (truncated), recommended owner badge (AE/CSM/BOTH), and `Open` button.
   - RevOps: run summary table (last 4 runs), funnel chart, signal-by-CSM and signal-by-AE tables.
   - Admin: same as RevOps + "Users" tab (stub).
3. **`/signal/[id]`** — full signal detail. Five sections rendered as the agent emitted them. Sticky right sidebar with metadata: confidence, priority band, ownership, draft outreach with copy-to-clipboard button. Bottom of page: "Mark Relevant / Not Relevant / Mark Actioned" buttons → POST to `/api/feedback`.
4. **`/notifications`** — disqualification transparency log for the current user's accounts. Each row: account name · gap detected · DQ rule · explanation · "Investigate" button (opens the account detail in read-only).
5. **`/accounts/[id]`** — read-only account context, useful when a notification needs investigation.
6. **`/runs`** (RevOps + Admin only) — list of historical runs, links to per-run summary.

### Backend API contract (FastAPI)

```
GET  /api/me                                # returns the fake-login identity
GET  /api/users                             # list of (role, name) seen in the latest run output
GET  /api/runs                              # list runs (RevOps/Admin)
GET  /api/runs/latest                       # latest run summary
GET  /api/signals?role={ae|csm|revops}&user={name}    # filtered queue
GET  /api/signals/{id}                      # full signal payload
GET  /api/notifications?role={ae|csm|revops}&user={name}
POST /api/feedback                          # {signal_id, relevant, actioned, notes}
GET  /api/accounts/{id}                     # read-only account context
POST /api/agent/run                         # kick off a new run (RevOps/Admin)
POST /api/agent/run/dry                     # dry-run, no LLM calls
```

The frontend reads from `output/*.json` via the API; it never reads files directly. This is the contract we'll honor in V1.5 when we replace files with Postgres queries — the frontend doesn't notice.

### UI tone

- shadcn/ui components, Tailwind. No custom design system in V1.
- Priority band: `high` = pink, `medium` = amber, `low` = gray.
- Draft outreach in a monospace card with "Copy" button.
- No bells. Function-first. The interface needs to be usable by an AE on Monday morning before coffee.

---

## 10. Repository layout (monorepo)

```
gtm-mesh/
├── README.md
├── RUN.md                              # generated by Claude Code in Phase 13
├── docs/
│   ├── Expansion_Agent_V1_Build_Spec.md    # this file
│   ├── GTM_Mesh_PRD_BRD_v1.docx            # reference
│   ├── RevOps_GTM_Roadmap_1.pdf            # reference
│   ├── Zuddl_ABM__Scoring_Framework__Framework.pdf
│   └── agent_brain.md                      # transcribed audio brief
├── data/
│   └── Expansion_Agent_1.xlsx
├── apps/
│   ├── agent/                          # Python (LangGraph)
│   │   ├── pyproject.toml              # uv-managed
│   │   ├── .env.example
│   │   ├── config/
│   │   │   ├── settings.py             # paths, model, caps, concurrency
│   │   │   ├── open_expansion_opps.py  # the 10 names
│   │   │   └── csm_roster.py           # name → slug
│   │   ├── prompts/
│   │   │   └── expansion_reasoning.py
│   │   ├── schemas/
│   │   │   ├── account_node.py
│   │   │   ├── account_context.py
│   │   │   ├── signal.py
│   │   │   └── notification.py
│   │   ├── src/
│   │   │   ├── repository.py           # loads xlsx, builds AccountNodes
│   │   │   ├── filter_logic.py         # DQ1–DQ5 + trigger
│   │   │   ├── rank_logic.py
│   │   │   ├── context_builder.py
│   │   │   ├── reasoning.py            # Claude call w/ JSON-mode
│   │   │   ├── persist.py              # writes run_log/* and output/*
│   │   │   └── graph/
│   │   │       ├── state.py            # AgentState TypedDict
│   │   │       ├── nodes.py            # filter_node, rank_node, etc.
│   │   │       └── build.py            # StateGraph compilation, Send fan-out
│   │   ├── cli.py                      # `python -m cli run|dry|replay|limit`
│   │   ├── tests/
│   │   │   ├── test_filter.py          # asserts 117→104→44 funnel
│   │   │   ├── test_rank.py
│   │   │   ├── test_schema.py
│   │   │   └── test_graph.py           # tests the LangGraph wiring
│   │   ├── run_log/                    # generated
│   │   └── output/                     # generated
│   ├── api/                            # FastAPI
│   │   ├── pyproject.toml
│   │   ├── main.py                     # serves output/*.json
│   │   ├── routes/
│   │   │   ├── signals.py
│   │   │   ├── notifications.py
│   │   │   ├── runs.py
│   │   │   ├── feedback.py
│   │   │   ├── accounts.py
│   │   │   └── agent.py                # kick-off endpoints
│   │   └── deps.py                     # fake-login resolver
│   └── web/                            # Next.js 14
│       ├── package.json
│       ├── app/
│       │   ├── layout.tsx
│       │   ├── login/page.tsx
│       │   ├── dashboard/page.tsx
│       │   ├── signal/[id]/page.tsx
│       │   ├── notifications/page.tsx
│       │   ├── accounts/[id]/page.tsx
│       │   └── runs/page.tsx
│       ├── components/
│       │   ├── SignalCard.tsx
│       │   ├── SignalDetail.tsx
│       │   ├── NotificationRow.tsx
│       │   ├── PriorityBadge.tsx
│       │   └── OwnerBadge.tsx
│       ├── lib/
│       │   ├── api.ts                  # fetch helpers
│       │   └── session.ts              # reads the fake-login cookie
│       └── tailwind.config.ts
├── Makefile                            # `make agent-run`, `make api`, `make web`, `make dev`
└── .gitignore
```

---

## 11. Dry-run analysis (measured on `Expansion_Agent_1.xlsx`)

### Funnel
| Stage | Count |
|---|---|
| Total customer accounts | 117 |
| Triggered (has gap) | 104 |
| After DQ1 Red adoption | 77 |
| After DQ2 Last Activity <30d | 54 |
| After DQ3 named open opp | 48 |
| After DQ4 Open Opp flag | 46 |
| After DQ5 inactive | **44 survivors** |

### Survivors split by AE
| AE | Survivors |
|---|---|
| Bhargav Prasad | 21 |
| Brooks Marsi | 16 |
| Mark Whalen | 6 |
| Paul Singh | 1 |

### Survivors split by CSM
| CSM | Survivors |
|---|---|
| Janhvi Gupta | 23 |
| Aastha Jindal | 11 |
| Saumitra Shekhar | 6 |
| Joe Huisman | 4 |

### Routing matrix (10 unique pairs)
See §3 Step 5.

### Gap distribution (104 triggered)
| Gap | Count |
|---|---|
| Webinar | 78 |
| Third-Party Events | 78 |
| Field Events | 37 |
| Conferences | 11 |

### Data coverage
| Source | Joined to Expansion Data accounts |
|---|---|
| Account-Data (by 15-char Account ID) | 117/117 |
| Gong+Fireflies rows | 117/117 (77 with Gong, 76 with Fireflies content) |
| Contacts_From_SF (by name) | 113/117 |
| Contacts Not in ProdSF (by name) | 113/117 |

### Cost envelope (per weekly run)
- 44 Claude calls × ~6k input tokens + ~1.5k output ≈ **265k input + 66k output tokens/week**.
- With Claude Opus pricing as of build date: **<$5/run**. Set `RUN_COST_CAP_USD=5` in `.env`.

---

## 12. Open data gaps and how V1 handles them

| Gap | V1 handling |
|---|---|
| "Same use case pitched in last 30–45 days" — no explicit field | Approximated by DQ2 (Last Activity <30d). Reasoning agent does secondary scan of Gong/Fireflies call titles + topics for the missing use case name; if a recent call mentions it, confidence downgrades and `reasoning_trace` notes it. |
| Usage trend (30/60/90 directional) — not in static sheet | V1 uses absolute volume via `usage_strength`. V2 adds trend buckets from product analytics. |
| Renewal date blank on some accounts | Default `renewal_proximity_score = 0.4` (neutral). Logged. |
| Persona buying role not explicit in `Contacts_From_SF` | Inferred by reasoning agent from Title + Seniority + Persona fields. Must justify in `who_to_target.why_this_person`. |
| Account ID length mismatch (18-char in Expansion Data, 15-char in Account-Data) | Repository normalizes by truncating to 15 when joining. |
| 4 expansion accounts unmatched to contacts | Agent still scores them; signal carries `data_quality_flag: "limited_persona_data"`. |
| Open Expansion Opp truth source: named list vs flag | Both are authoritative; either triggers DQ. Named list wins on disagreement. |
| 14 accounts have no CSM (broader Account-Data); 0 of these survive | Repository handles `csm = None`: signal routes to AE only, flagged. |

---

## 13. Operational guardrails

- **Idempotency.** `run_id = YYYYMMDD-HHMMSS`. Re-running on same data is safe.
- **Cost guard.** `RUN_COST_CAP_USD=5`. Orchestrator halts at 90% with a clean checkpoint.
- **Concurrency.** `max_concurrency=8` LLM calls. Tenacity backoff on 429/500.
- **Replay.** `cli.py replay <run_id>` reuses persisted contexts. No re-assembly.
- **Dry run.** `cli.py dry-run` walks filter + rank + assemble; skips LLM. Validates funnel.
- **PII discipline.** Contact emails passed to LLM (needed for outreach). Flagged `pii_present=true` in run log for future redaction policy.
- **Hallucination guard.** Every concrete claim in `draft_outreach` must cite a bullet in `supporting_context`. Validator checks for orphan facts (post-V1 enhancement; structural placeholder in V1).

---

## 14. Validation plan

V1 is "done" when:
1. **Funnel test passes** — `tests/test_filter.py` asserts 117 → 104 → 77 → 54 → 48 → 46 → 44.
2. **Schema enforcement** — 100% of Claude responses pass `Signal` validation across a full run.
3. **Dry-run** completes in <30s for 117 accounts.
4. **Full run** completes in <5 min for 44 candidates.
5. **Frontend** renders the queue for at least one AE and one CSM without errors.
6. **Backtest** (post-V1, with historical data): precision ≥ 60%, recall ≥ 50%.
7. **Shadow** (4 weeks of CSM review): relevance rating ≥ 70%.

---

## 15. Sheet-to-field reference card

**Expansion Data** (headers in row 2)

| Col | Field | Used for |
|---|---|---|
| A | 18-digit Account Id | join key (truncate to 15) |
| B | Account Name | display, contact joins |
| D | Account Owner | (deprecated for routing — see note) |
| E | Account Segment | context |
| F | ACV | context |
| K | Use case gap | **trigger** |
| L–R | Event counts by type | usage_strength, gap validation |
| S | Adoption Health from Prod | **DQ1**, priority modifier |
| T | Target Departments | context |
| U | Sales Model | context |
| V | Target Customers | context |
| W–Z | ICP counts (Clay) | persona supply |
| AA–AC | Hiring counts | 3P signal |
| AD–AG | ICP users from Prod | persona corroboration |
| AH–AK | ICP contacts not in prod | persona supply |

> **Note on `Expansion Data!D`**: this column is misleadingly named. The authoritative AE/CSM lives in `Account-Data`. The repository overrides this column on every join.

**Account-Data** (headers in row 1, 319 cols)

| Col | Field | Used for |
|---|---|---|
| 3 (C) | Account Owner | **AE name** |
| 10 (J) | Account ID | join key |
| 33 (AG) | Last Activity | **DQ2** |
| 38 (AL) | Owner Role | AE role badge |
| 78 (BZ) | Active Account | DQ5 |
| 126 (DV) | CSM owner | **CSM name** |
| 196 (GN) | Has Open Expansion Opp? | **DQ4** |
| 198 (GP) | Health Status | context |
| 205 (GW) | Inactive > 90 days? | DQ5 |
| 207 (GY) | Is Active Customer | **DQ5** |
| 255 (IU) | Plan End Date | renewal_proximity |
| K/L/M | 1P/2P/3P engagement scores | signals |

**Gong+Fireflies Transcripts** (row 1)

| Col | Field | Used for |
|---|---|---|
| C | Account ID | join key |
| J | Gong Business Summary | narrative |
| K | Gong Product Interests | gap validation |
| L | Gong Competitors Mentioned | 3P signal |
| M | Gong Key Points | context |
| Q | Fireflies Overview | context |
| R | Fireflies Action Items | context |
| S | Fireflies Topics | gap validation |

**Contacts_From_SF**: First/Last Name, Title, Account Name (join), Email, LinkedIn, Persona Fit Score, Seniority, Persona.
**Contacts Not in ProdSF**: Account Name (join), Contact Name, Title, LinkedIn, per-use-case flags (Conferences/Webinar/Field Events/Third-Party Events), Email, Found in Prod?

---

## 16. WHAT TO DO — step-by-step

### A) Attach to Claude Code

Drop all of these in the project root before your first prompt:

1. **This spec** — `docs/Expansion_Agent_V1_Build_Spec.md` (this file).
2. **GTM_Mesh_PRD_BRD_v1.docx** — `docs/` (Claude Code reads §3 + §4 for the V1.5 forward-compat mapping).
3. **RevOps_GTM_Roadmap_1.pdf** — `docs/` (Phase 0 + Phase 1 context).
4. **Zuddl_ABM__Scoring_Framework__Framework.pdf** — `docs/` (scoring backbone, used in V2; V1 references only).
5. **agent_brain.md** — `docs/`. Paste your audio transcript into a new markdown file. This is the V1 ground truth for the flow.
6. **`data/Expansion_Agent_1.xlsx`** — the dataset.

### B) The Claude Code build prompt — paste this verbatim as message 1

> You are building the V1 Expansion Agent for Zuddl's GTM Mesh, a local monorepo at `gtm-mesh/`. The full spec is in `docs/Expansion_Agent_V1_Build_Spec.md`. The dataset is `data/Expansion_Agent_1.xlsx`. Read the spec end-to-end before writing code. Cross-reference `docs/GTM_Mesh_PRD_BRD_v1.docx` and `docs/agent_brain.md` for intent.
>
> **Stack:** Python 3.11 + LangGraph + Claude API (anthropic SDK) for `apps/agent/`. FastAPI for `apps/api/`. Next.js 14 + Tailwind + shadcn/ui for `apps/web/`. Use `uv` for Python env management. Use `pnpm` for the Next.js app.
>
> **Build in this order. Do not move on until the previous phase is green.**
>
> **Phase 0 — Scaffold.** Create the monorepo per §10. Initialize git. Add a root `Makefile` with `make agent-run`, `make agent-dry`, `make api`, `make web`, `make dev` (runs API + web concurrently). Add `.env.example` with `ANTHROPIC_API_KEY`, `RUN_COST_CAP_USD=5`, `MAX_CONCURRENCY=8`, `MODEL=claude-opus-4-7`. Add `README.md` pointing to the spec.
>
> **Phase 1 — Schemas.** Build `apps/agent/schemas/{account_node,account_context,signal,notification}.py` as strict Pydantic v2 models matching §5 and §7. Add round-trip tests (`tests/test_schema.py`).
>
> **Phase 2 — Repository.** `apps/agent/src/repository.py` loads the 7 sheets once and builds an `AccountNode` per account, joined across all 5 source sheets. **CRITICAL:** AE = `Account-Data!C` (col 3, "Account Owner"). CSM = `Account-Data!DV` (col 126, "CSM owner"). Owner role = `Account-Data!AL` (col 38). The `Expansion Data!D` "Account Owner" column is unreliable — always override from Account-Data. Normalize 18-char Account IDs to 15. Log all join misses to `run_log/data_quality.csv`. Handle missing CSM by routing to AE only with a flag.
>
> **Phase 3 — Filter logic.** `apps/agent/src/filter_logic.py` implements trigger (Step 1) + 5 disqualifiers (Step 2) per §3. **`tests/test_filter.py` must assert exactly: 117 → 104 (trigger) → 77 (after DQ1) → 54 (after DQ2) → 48 (after DQ3) → 46 (after DQ4) → 44 (after DQ5)**. Do not move on until this test passes against the real xlsx.
>
> **Phase 4 — Rank logic.** `apps/agent/src/rank_logic.py` implements §3 Step 3 deterministic priority. Add unit tests.
>
> **Phase 5 — Context builder.** `apps/agent/src/context_builder.py` produces the AccountContext from an AccountNode. Token-cap to ~6000 with the prune order in §5. Add a snapshot test on one known account (Zenoti or another from the survivor list).
>
> **Phase 6 — Reasoning.** `apps/agent/src/reasoning.py` exposes `async def score_account(context) -> Signal`. Uses Claude with response format = JSON (matching the §7 schema) and the prompt from `prompts/expansion_reasoning.py`. Tenacity backoff. Validate response; on failure retry once with the validation error appended; final failure → `is_signal=false` with `validation_error`.
>
> **Phase 7 — LangGraph.** `apps/agent/src/graph/{state,nodes,build}.py`. Build the StateGraph per §2 with these nodes: `load_accounts`, `filter_node`, `notify_disqualified`, `rank_node`, `assemble_node`, `reasoning_node` (uses `Send` API for fan-out), `cap_node`, `persist_node`. Use `MemorySaver` for V1 checkpointing (it will become `PostgresSaver` in V1.5 — keep the dependency injection clean). Conditional edges for `dry-run` mode that skips `reasoning_node` and `cap_node`. The graph must compile and `app.get_graph().draw_png("docs/graph.png")` should produce a flow diagram.
>
> **Phase 8 — Persistence.** `apps/agent/src/persist.py` writes to `run_log/` and `output/` per §8. The output JSON files are the data contract for the API.
>
> **Phase 9 — CLI.** `apps/agent/cli.py` with subcommands: `run`, `dry-run`, `replay <run_id>`, `limit <N>`. Use `typer` and `rich` for output. After `dry-run` runs end-to-end on the 117 accounts and produces the funnel, gate to Phase 10.
>
> **Phase 10 — API.** `apps/api/` per the endpoints in §9. Reads from `output/*.json`. The `deps.py` exposes a fake-login dependency that reads the `role` and `user` from cookies. No DB. CORS open in V1.
>
> **Phase 11 — Frontend.** `apps/web/` per §9. Start with `/login` (the fake login dropdown — populate user options by reading `/api/users` which the API derives from the run output). Then build `/dashboard`, `/signal/[id]`, `/notifications`, `/accounts/[id]`, `/runs`. shadcn/ui components; Tailwind. No auth wiring — just the cookie. Use server components where possible, client components only for the buttons/forms.
>
> **Phase 12 — End-to-end.** `make dev` brings up API + web. Login as Bhargav (AE) — see 5 signals; login as Janhvi Gupta (CSM) — see 5 signals; login as RevOps user — see all 44 (or however many survived this run). Open one signal, click "Mark Relevant" — it writes to `outcomes.csv`.
>
> **Phase 13 — Documentation.** Generate `RUN.md` with: prerequisites, env setup, first-run instructions, how to interpret outputs, how to replay, how the V1.5 migration will work.
>
> **Hard rules across all phases:**
> - Every Claude response is schema-validated. No exceptions.
> - Every disqualified account produces a notification — that's the transparency contract.
> - The LangGraph nodes never reach into files directly — they go through repository / persist. This is what lets V1.5 swap to Postgres without touching `graph/`.
> - Ask before guessing. Anything not in the spec is something we discuss, not invent.
> - `prompts/expansion_reasoning.py` is a config artifact — version it, never inline-edit from code.
> - Keep `apps/agent/` and `apps/api/` as separate Python projects with separate pyproject.tomls — the agent has heavy deps, the API stays lean.

### C) Run order, first time

```bash
# 0. Prerequisites: Python 3.11+, Node 20+, uv, pnpm
make scaffold-check                        # validates env

# 1. Install
cd apps/agent && uv sync
cd ../api    && uv sync
cd ../web    && pnpm install

# 2. Sanity check — funnel only, no LLM
cd ../agent && uv run python -m cli dry-run
# Expect: "117 → 104 → 77 → 54 → 48 → 46 → 44 survivors" + per-AE / per-CSM tables

# 3. Limited LLM run — 3 accounts, validates the reasoning path
uv run python -m cli limit 3

# 4. Full run — 44 LLM calls, writes to output/
uv run python -m cli run

# 5. Bring up the app
cd ../.. && make dev
# API on :8000, web on :3000

# 6. Open http://localhost:3000/login
#    Try: AE / Bhargav Prasad   → queue with up to 5 signals
#         CSM / Janhvi Gupta    → queue with up to 5 signals
#         RevOps / any name     → all signals, run summary, funnel
```

### D) What you ship to Claude Code, summarized

| File | Why |
|---|---|
| `docs/Expansion_Agent_V1_Build_Spec.md` (this) | The build brief |
| `docs/GTM_Mesh_PRD_BRD_v1.docx` | Architecture reference for V1.5 forward compat |
| `docs/RevOps_GTM_Roadmap_1.pdf` | Phase context |
| `docs/Zuddl_ABM__Scoring_Framework__Framework.pdf` | Scoring backbone reference |
| `docs/agent_brain.md` | The voice-brief transcript — your authoritative business intent |
| `data/Expansion_Agent_1.xlsx` | The dataset |

And paste **§16.B "The Claude Code build prompt"** as your first message.

---

*End of spec.*
