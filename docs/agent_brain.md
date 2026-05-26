# Expansion Agent — Brain Dump (voice brief → markdown)

The exact flow as described by the owner. This is the V1 ground truth for business intent. Anywhere this disagrees with the build spec, the build spec wins (the spec has already reconciled ambiguity), but the *why* lives here.

---

## Step 1 — Trigger detection (use case gap)

For every customer account, check column K (Use case gap) in Expansion Data. If a missing use case exists, the account passes the trigger.

> In V1 there's no real-time trigger because data is static — the agent runs on schedule across all ~118 accounts and treats column K as the trigger condition.

## Step 2 — Disqualifiers (five)

An account with a use case gap is disqualified if **any** of these are true:

1. **Adoption health is Low / Red** (column S in Expansion Data, or equivalent in Account-Data).
2. **Last Activity within the last 30 days** (column AG in Account-Data) — they were recently engaged, likely pitched.
3. **Open expansion opportunity exists** — the 10-account list:
   T. Rowe Price · CrowdStrike · Fullscript · Under Armour · Figma · Turnitin · BigCommerce · Iterable · Tricentis · Postman.
4. **Open Expansion Opp flag** in Account-Data (col 196).
5. **Account is inactive** (Account-Data col 207 `Is Active Customer` = 0, OR col 205 `Inactive > 90 days?` > 0).

> Note from brief reconciliation: the spoken version listed 4 explicit rules; the PRD's "pitched in last 30–45 days" is folded into DQ2 (Last Activity <30d). The build spec splits the flag + named-list versions into DQ3 and DQ4 to mirror the data sources.

**Critical behavior:** disqualified accounts don't disappear silently. Each one fires a **notification** to the CSM *and* the AE: *"Acme had a Field Events gap but was disqualified because [reason]. Want to know more?"* This is a transparency requirement, not a polish item.

## Step 3 — Priority modifier (ranking)

Surviving accounts get ranked by a composite of:

- **Adoption health.** Green > Yellow > Red (Red shouldn't survive Step 2, treat as guardrail).
- **Renewal proximity.** 0–120 days = higher priority; >120 days = lower.
- **Usage strength.** Heavy product users rank higher than light users.

Deterministic, runs before any LLM call.

## Step 4 — Context assembly

For each surviving account, pull together:

- Use case gap details (what's missing, what's adjacent).
- Usage trend (volume, direction — V1 uses absolute volume).
- **1P signals** — Factors intent, demo/pricing visits, form fills (from Account-Data).
- **2P signals** — Clay/Apify/Serper: LinkedIn engagement, Zuddl mentions, champion job moves.
- **3P signals** — hiring for event roles, competitor mentions on G2/LinkedIn, event leader hired in last 90 days.
- **Gong + Fireflies summaries** — call titles, business summary, product interests, competitors mentioned, key points, action items, topics, keywords.
- Hiring signals, champion moves, website behavior, anything else relevant.

This becomes the **AccountContext** object passed to the reasoning agent.

## Step 5 — Reasoning + persona selection

The reasoning agent:

1. **Identifies the pain point** tied to the use case gap, grounded in context (Gong quote, hiring signal, competitor mention, etc.).
2. **Picks who to target.** Two persona pools:
   - `Contacts_From_SF` (~2,173 rows) — already in product/CRM, with Persona Fit Score, Account Fit Score, Seniority, Persona.
   - `Contacts Not in ProdSF` (~878 rows) — Clay-found ICPs at customer accounts, not yet in product, tagged by event-type relevance.
3. Compares across both pools, picks the best persona match for that specific use case gap, and assigns a buying role.

## Step 6 — Routing + top-N capping

Every account has both an **AE** (Account-Data col C) and a **CSM** (Account-Data col DV). The orchestrator:

- Groups ranked signals by AE and by CSM independently.
- Caps each AE's and each CSM's queue to **top 5 per week** by final_score.
- The same account fires into both queues (dual-routing — the transparency contract).

> Brief said "top 5 per CSM per 2-week cycle"; PRD said "3–5 per week". The build spec lands on **top 5 per week per role**.

## Step 7 — Output per account (what the CSM/AE sees)

Five sections, in this order:

1. **Why now** — why this account should be the priority for the next 2 weeks.
2. **What's missing** — the use case gap, explained in business terms.
3. **Who to target** — named persona(s) with title, buying role, source (SF / Clay), and why this person.
4. **Supporting context** — the reasoning trace: what the agent saw, what logic it applied, key signals.
5. **Draft outreach** — a business-grade email, ready to send with minor edits. Personalized to the persona and the gap.

---

*This brain dump is the business intent. The build spec at `docs/Expansion_Agent_V1_Build_Spec.md` is the operational truth.*
