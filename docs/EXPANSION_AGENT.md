# Expansion Agent — How It Works

*Field-by-field walkthrough. What data the agent reads, how it filters, how
it scores, how it picks who to email, how it writes the output, and why it
explains every decision.*

Read alongside [ARCHITECTURE.md](ARCHITECTURE.md), which covers the system
shape. This doc is about the **agent's reasoning logic**.

---

## 1 · The job in one sentence

> For every customer account, decide whether there is a high-confidence
> *expansion play* this week, identify *who* to talk to, *why now*, and
> *what to say* — backed by evidence the AE or CSM can verify in 30 seconds.

The agent processes **117 customer accounts** in V1. Out of those, **104**
have a use-case gap. After 5 disqualifiers, **44** survive to LLM reasoning.
Each rep gets the **top 5 capped queue** for the week.

---

## 2 · The six-step pipeline

```
117 accounts
   │
   ▼  Step 1 — Trigger detection (1 field check)
104 triggered
   │
   ▼  Step 2 — Disqualifiers (5 rules, first hit wins)
44 survivors    ┐
   │            │ 60 dropped → notifications to AE + CSM
   ▼  Step 3 — Deterministic ranking (3-component weighted score)
44 ranked
   │
   ▼  Step 4 — Context assembly (one ~6,000-token packet per account)
44 contexts
   │
   ▼  Step 5 — LLM reasoning (one Claude/OpenAI call per account, parallel)
43 valid signals + 1 self-reject
   │
   ▼  Step 6 — Capping + routing (top 5 per AE, top 5 per CSM)
Up to 5 signals per rep in the dashboard
```

Steps 1–3 are pure deterministic Python — no LLM, ~30 seconds for the full
117. Step 5 is where the LLM does the actual judgment. Step 6 makes sure
nobody gets more than they can act on.

---

## 3 · Step 1 — Trigger detection

**Input field:** `Expansion Data!K` — *"Use case gap (Prod data and usecase 2025)"*

**Rule:** Account triggers if this column has any non-empty value.

**Implementation:** [`apps/agent/src/filter_logic.py`](../apps/agent/src/filter_logic.py)
function `is_triggered()`.

```python
def is_triggered(node: AccountNode) -> bool:
    return bool(node.use_case_gap_field and node.use_case_gap_field.strip())
```

**Why this column:** It's the system's pre-computed "where could this
account expand?" hint, derived from comparing the account's 2025 use-case
list against actual product usage. If column K is blank, the customer is
already using everything they bought — no expansion conversation to have.

**Measured result on V1 data:** 104 / 117 trigger. The 13 that don't are
written to `run_log/non_triggered.csv` — full transparency.

---

## 4 · Step 2 — The five disqualifiers

If **any** of these is true on a triggered account, the agent drops it from
the queue and emits a **Notification** to both the AE and the CSM. The
disqualifier explains *why*, so reps don't wonder where the account went.

### DQ1 — Red adoption

| | |
|---|---|
| **Source** | `Expansion Data!S` *(Adoption Health from Prod)* |
| **Rule** | value = `Red` (case-insensitive) |
| **Why** | If an account isn't using what they already have, expansion conversations land badly. Adoption needs to recover first. |
| **Measured drops** | 27 / 104 |

### DQ2 — Recent activity (already engaged)

| | |
|---|---|
| **Source** | `Account-Data!AG` *(Last Activity)* |
| **Rule** | `today − last_activity < 30 days` |
| **Why** | If we touched this customer in the last month, they were probably already pitched something. Don't dogpile. (This also covers the spoken brief's "pitched in the last 30–45 days" rule.) |
| **Measured drops** | 23 |

### DQ3 — Named open opportunity

| | |
|---|---|
| **Source** | hardcoded list in [`apps/agent/config/open_expansion_opps.py`](../apps/agent/config/open_expansion_opps.py) |
| **Rule** | account name in the list (case-insensitive, trimmed) |
| **List** | T. Rowe Price · CrowdStrike · Fullscript · Under Armour · Figma · Turnitin · BigCommerce · Iterable · Tricentis · Postman |
| **Why** | These 10 accounts already have an open expansion oppo in flight — the AE is working it. Surfacing a "new" signal would cause confusion. |
| **Measured drops** | 6 |

### DQ4 — Open Expansion Opp flag

| | |
|---|---|
| **Source** | `Account-Data!GN` *(Has Open Expansion Opp? — col 196)* |
| **Rule** | value > 0 |
| **Why** | Salesforce already says this account has a pending expansion deal. Same reasoning as DQ3 — don't double-touch. |
| **Measured drops** | 2 |

### DQ5 — Inactive customer

| | |
|---|---|
| **Source** | `Account-Data!GY` *(Is Active Customer — col 207)* OR `Account-Data!GW` *(Inactive > 90 days? — col 205)* |
| **Rule** | `Is Active Customer = 0` **or** `Inactive > 90 days? > 0` |
| **Why** | The account is dormant or churned. Expansion isn't the play; recovery is. |
| **Measured drops** | 2 |

### Order matters (first hit wins)

Disqualifiers run in order DQ1 → DQ5. If an account is both Red-adoption
and inactive, it gets logged under DQ1 (the first hit). This makes the
funnel cleanly subtractive: `104 → 77 → 54 → 48 → 46 → 44`.

### Every drop produces a Notification

```jsonc
{
  "account_id": "0015i00000Y44gl",
  "account_name": "Grafana Labs",
  "ae": "Bhargav Prasad",
  "csm": "Aastha Jindal",
  "detected_gap": "Field Events; Webinar; Third-Party Events",
  "disqualifier_rule": "DQ4_open_opp_flag",
  "explanation": "Account-Data flags an open expansion opportunity — AE already working it.",
  "want_more_info": true
}
```

The AE and the CSM both see this in their `/notifications` view with an
"Investigate" button that opens the full account context. **Transparency is
not a polish item — it's a contract.**

---

## 5 · Step 3 — Deterministic ranking

Survivors get a `priority_score` ∈ [0, 1] from a weighted formula. No LLM
involved. Auditable, replayable, instantly explainable.

```
priority_score =  0.40 × adoption_score
               +  0.30 × renewal_proximity_score
               +  0.30 × usage_strength
```

### Component 1 — `adoption_score` (40% weight)

| Adoption Health | Score |
|---|---|
| Green | 1.0 |
| Yellow | 0.6 |
| Red | 0.2 *(shouldn't survive DQ1, treated as guardrail)* |
| Missing | 0.4 *(neutral fallback)* |

**Source:** `Expansion Data!S`. **Why 40%:** Adoption is the strongest single
predictor of expansion success. A Green customer who's missing a use case
is the textbook play.

### Component 2 — `renewal_proximity_score` (30% weight)

| Days to renewal | Score |
|---|---|
| ≤ 120 days | 1.0 |
| 121–180 days | 0.6 |
| 181–365 days | 0.3 |
| > 365 days | 0.1 |
| past due | 1.0 *(treated as imminent)* |
| missing | 0.4 |

**Source:** `Account-Data!IU` *(Plan End Date — col 255)*, falling back to
`Account-Data!HJ` *(Latest Expansion Contract End — col 218)*.

**Why 30%:** Renewal urgency creates the right negotiating window. 120 days
out is when procurement starts taking the call.

### Component 3 — `usage_strength` (30% weight)

```
total_events_all_time = field_events + third_party_events + webinars
                       + standard_in_person + standard_hybrid + standard_virtual

usage_strength = log1p(total_events) / log1p(max_total_across_survivors)
```

**Source:** `Expansion Data!L–R` *(per-event-type all-time counts)*.

**Why log normalization:** A customer who ran 100 events is meaningfully
heavier than one who ran 0, but not 100× heavier — the log curve compresses
the long tail so a top-tier user doesn't crowd out the entire ranking.

**Why 30%:** Heavy product users have an internal champion. Their CSM has
something to reinforce. They're more likely to say yes to a second use case.

### Implementation

[`apps/agent/src/rank_logic.py`](../apps/agent/src/rank_logic.py) — pure
Python, fully unit-tested.

---

## 6 · Step 4 — Context assembly

Before calling the LLM, the agent builds an `AccountContext` per candidate.
Think of it as the "briefing packet" the agent reads.

### What goes into the packet

| Section | Fields |
|---|---|
| Identity | account_id, account_name, domain |
| Ownership | AE name + role, CSM name |
| Profile | segment, ACV, target_departments, sales_model, target_customers |
| Current state | adoption_health, active_use_cases_in_prod, use_case_gap_field, renewal_proximity_days, is_active_customer, has_open_expansion_opp, last_activity_days_ago |
| Usage | per-event-type counts (field/third-party/webinars/standard variants) + total |
| 1P signals | factors_intent_label, demo_pricing_visits_90d, factors_last_intent_date |
| 2P signals | linkedin_engagement_30d, zuddl_mentions, champion_job_moves_90d |
| 3P signals | event_role_hiring_90d, competitor_mentions_g2_90d, competitor_in_stack |
| ICP supply | conferences_icp_count, field_events_icp_count, webinar_icp_count, third_party_icp_count |
| Conversations | gong_business_summary, gong_product_interests, gong_competitors_mentioned, gong_key_points, fireflies_overview, fireflies_action_items, fireflies_topics |
| Contacts in product | up to N SF contacts with title, seniority, persona, persona_fit_score, LinkedIn, email |
| Contacts not in product (Clay) | up to N ICPs found at the account, tagged by relevant use case |
| Deterministic score | priority_score from Step 3 |

### The 6,000-token budget

Larger contexts cost more and confuse the model. Cap is enforced by the
context builder. If a packet is oversize, prune in this order:

1. Drop call transcript bullets (keep summaries only)
2. Trim contact lists to top 8 by persona-fit score
3. Trim signal arrays to top 5 each
4. Truncate long summaries to 1,500 chars

**Source:** [`apps/agent/src/context_builder.py`](../apps/agent/src/context_builder.py).
All 44 survivors fit comfortably under cap in V1.

---

## 7 · Step 5 — LLM reasoning

This is where the agent actually thinks.

**One call per candidate, in parallel** (up to 8 concurrent), schema-validated
on the way out. The reasoning is governed by the system prompt at
[`apps/agent/prompts/expansion_reasoning.py`](../apps/agent/prompts/expansion_reasoning.py),
which the agent follows in this order:

### 5.1 — Confirm the gap is real

The use-case-gap-field is the *system's best guess*. The agent validates by
checking:

- The corresponding usage column should be 0 or near-zero
- Conversation data should not contradict it (they may have run a field
  event via workaround)
- 1P / 2P / 3P signals should lean toward NEED (intent visits, role hiring,
  competitor in stack)

If the gap is not confirmed, the agent returns `is_signal=false` with a
one-line reason. **In the live V1 run, 1 of 44 candidates self-rejected
this way** — that's the system working as designed.

### 5.2 — Identify the pain point

Tie the gap to a concrete pain or initiative grounded in evidence:

- A Gong quote — "we're struggling with our webinar tooling"
- A hiring signal — "Field Marketing Manager just opened on LinkedIn"
- A funding event
- A competitor mention — "Hopin is in their stack today"

Generic statements are not acceptable. The agent's `supporting_context`
bullets must cite these specific signals.

### 5.3 — Choose the target persona

Two pools to compare:

| Pool | What it is |
|---|---|
| **Contacts in product (SF)** | Existing user persona — warmer entry, already a user |
| **Contacts not in product (Clay)** | ICP found by Clay/Apify but not yet in the product |

Selection criteria (applied in order):

| Criterion | Detail |
|---|---|
| **(a) Title relevance to the gap** | Field Events → "Head of Events", "Field Marketing Manager", "Demand Gen Lead". Webinars → "Marketing Ops", "Demand Gen", "Content Marketing Lead". Third-Party → "Field Marketing Manager", "Event Marketing". |
| **(b) Seniority** | Sufficient to influence a buying decision. |
| **(c) Buying role** | Economic Buyer > Champion > Influencer > User |
| **(d) Tiebreaker** | Prefer SF contact (already a user) **unless** Clay contact is a clearly better persona fit — then prefer Clay and flag they're not yet in product. |

Output names ONE primary (optionally one secondary).

### 5.4 — Recommend the action owner

| Action owner | When |
|---|---|
| **CSM** | Adoption-led play: existing user persona, gap surfaced by usage, renewal proximity drives urgency. |
| **AE** | Buyer-led play: Clay-found new persona, new initiative based on hiring/intent, no existing relationship inside the account. |
| **BOTH** | Both routes are strong (high confidence + multiple personas). |

This is *routing intelligence*, not just metadata. The CSM and AE both see
the signal, but the badge tells them who should lead.

### 5.5 — Write the five-section output

This is the deliverable. Exactly five named sections, in this order:

1. **why_now** — 2–3 sentences, concrete, time-bound, evidence-anchored.
2. **whats_missing** — the gap, in business terms the rep can repeat back to the customer.
3. **who_to_target** — named persona, title, buying role, source (`sf` | `clay`), LinkedIn, one-line "why this person".
4. **supporting_context** — 3–6 bullets, each citing a specific signal or quote. This is the audit trail.
5. **draft_outreach** — full email: subject + 3–5 short paragraphs + signoff. No hallucinated facts.

### 5.6 — Score confidence (0..1)

The agent rates its own certainty. `confidence > 0.75` (i.e. **high**) requires:

- Gap confirmed
- Named persona with strong fit
- **≥ 2 corroborating signals from different categories** (e.g. a conversation cue PLUS a 3P signal)

This is the soft check that gets reflected in the priority band.

### Schema enforcement

Every LLM response must validate against the `Signal` Pydantic schema in
[`apps/agent/schemas/signal.py`](../apps/agent/schemas/signal.py).

If validation fails:
1. **Retry once**, appending the validation error to the prompt as a hint.
2. If it fails again, return `is_signal=false` with `reasoning_trace="validation_error: ..."`.

**No bad data ever lands in `output/*.json`.** That's the contract.

---

## 8 · Step 6 — Capping, routing, and priority bands

### Final score

Once a signal is back from the LLM, the orchestrator computes:

```
final_score = 0.5 × LLM_confidence + 0.5 × priority_score
```

Half-and-half: the LLM's judgment plus the deterministic rank. Neither is
allowed to dominate.

### Priority bands

| Band | Threshold | UI color |
|---|---|---|
| **high** | `final_score ≥ 0.70` | pink |
| **medium** | `0.45 ≤ final_score < 0.70` | amber |
| **low** | `final_score < 0.45` | gray (never delivered — floor) |

### Capping rules

- **Each AE: top 5 per week** by `final_score`
- **Each CSM: top 5 per week** by `final_score`
- **Dual routing.** Every signal has both an AE and a CSM. It lands in both
  queues independently. If the AE's queue is full but the CSM's isn't, the
  signal still appears in the CSM queue.
- **Low-band floor.** Signals with `priority_band="low"` are never delivered,
  even if a queue has room.

### Routing in practice (real numbers from the V1 run)

| AE | Signals delivered | | CSM | Signals delivered |
|---|---|---|---|---|
| Bhargav Prasad | 5 | | Janhvi Gupta | 5 |
| Brooks Marsi | 5 | | Aastha Jindal | 5 |
| Mark Whalen | 5 | | Saumitra Shekhar | 5 |
| Paul Singh | 1 *(only 1 survivor in his book)* | | Joe Huisman | 4 |

13 accounts in V1 are jointly owned by Bhargav + Janhvi — they each see
those same signals in their queues. That's dual-routing working as designed.

---

## 9 · The full output schema (what the UI renders)

Every successful signal looks like this:

```jsonc
{
  "account_id": "001J300000L4VdS",
  "account_name": "Sonar",
  "is_signal": true,

  "missing_use_case": "Webinar",
  "confidence": 0.80,
  "priority_band": "high",
  "recommended_action_owner": "BOTH",

  "ownership": {
    "ae":  {"name": "Bhargav Prasad", "role": "AE (APAC)"},
    "csm": {"name": "Aastha Jindal"}
  },

  "why_now": "Sonar is experiencing challenges with the integration of their webinar module… With renewal approaching in 43 days, this creates a time-sensitive opportunity to demonstrate how Zuddl can enhance their event capabilities.",

  "whats_missing": "Sonar has not maximized the use of webinars due to integration issues and is seeking more efficient solutions for their event management.",

  "who_to_target": {
    "primary": {
      "name": "Harry Wang",
      "title": "Chief Growth Officer, EVP",
      "buying_role": "economic_buyer",
      "source": "clay",
      "linkedin": "https://linkedin.com/in/...",
      "why_this_person": "As the Chief Growth Officer, Harry has the authority to drive initiatives that improve their event operations."
    },
    "secondary": null
  },

  "supporting_context": [
    "Conversations highlighted significant limitations with the Salesforce integration affecting webinar functionality.",
    "Sonar is looking for solutions to streamline their webinar processes, particularly around attendee experience.",
    "The upcoming release of Zuddl's simulive feature is directly relevant to address the identified challenges."
  ],

  "draft_outreach": {
    "subject": "Enhancing Your Webinar Experience with Zuddl",
    "body": "Hi Harry,\n\nI hope this message finds you well. I wanted to reach out as we are aware of some challenges Sonar has faced with the Salesforce integration affecting your webinar functionalities…"
  },

  "reasoning_trace": "Confirmed the gap is real as third-party events usage is zero; conversations indicate challenges with webinar integration limiting usage. Target persona is identified based on role and influence within the organization, with support from multiple signals highlighting the urgency of the need for enhancement.",

  "priority_score": 0.95,
  "final_score":    0.88,

  "model_metadata": {
    "model": "gpt-4o-mini",
    "tokens_in": 2731,
    "tokens_out": 622,
    "latency_ms": 24019
  },
  "pii_present": false
}
```

The web app at `/signal/[id]` renders this exact JSON into the five
on-screen sections, plus a sticky sidebar with the metadata.

---

## 10 · "Why did the agent give *this* output?" — the audit trail

Every signal carries three layers of explanation:

| Layer | Where to find it | What it tells you |
|---|---|---|
| **The pitch** | `why_now`, `whats_missing` | The business rationale, in the rep's language |
| **The persona pick** | `who_to_target.primary.why_this_person` | Why this person, not someone else |
| **The evidence** | `supporting_context` (3–6 bullets) | Each bullet cites a specific Gong quote, hiring count, ICP match, competitor mention — the audit trail the rep can verify in 30 seconds |
| **The inference** | `reasoning_trace` | Step-by-step: gap confirmed by [X], persona matched on [Y], confidence [Z] because [reason]. Not shown to customer — shown to the rep + RevOps. |
| **The math** | `priority_score`, `confidence`, `final_score` | The deterministic component, the LLM's self-assessment, and the combined score that drove placement in the queue. |

Combined, this answers: *Why did Sonar end up at the top of Bhargav's
queue this week, and why is the agent recommending Harry Wang rather than
the SF-known Director of Marketing?*

Every claim in the draft email must be grounded in `supporting_context`.
Hallucinations show up as orphan facts — claims with no matching evidence
bullet. The structural placeholder is in V1; a strict orphan-fact validator
ships in V1.5.

---

## 11 · Transparency for dropped accounts

The agent doesn't just hand back winners — every disqualified account
produces a `Notification` saying *what gap was detected* and *why we
skipped it this week*.

```jsonc
{
  "account_id": "0015i00000Y44gl",
  "account_name": "Grafana Labs",
  "ae": "Bhargav Prasad",
  "csm": "Aastha Jindal",
  "detected_gap": "Field Events; Webinar; Third-Party Events",
  "disqualifier_rule": "DQ4_open_opp_flag",
  "explanation": "Account-Data flags an open expansion opportunity — AE already working it.",
  "want_more_info": true
}
```

Both the AE and the CSM see this on `/notifications`. Each row has an
**Investigate** button that opens the raw account context, so the rep can
override the agent ("actually that open opp was closed-lost, please surface
this") and bring the account back into consideration manually.

That's the second half of the contract: **the agent never makes a routing
decision the rep can't see and override.**

---

## 12 · What the rep sees on Monday morning

1. **Open `/dashboard`.** Five cards. Each shows: account name, missing
   use case, priority band, recommended owner badge, why-now teaser, score.
2. **Click a card.** Five-section breakdown:
   1. Why now
   2. What's missing
   3. Who to target (with Best-Persona callout: name, title, buying role,
      source, LinkedIn, why-this-person)
   4. Supporting context (3–6 evidence bullets)
   5. Draft outreach email (subject + body + **Copy** button)
3. **Reviewer the inference.** Sticky sidebar shows confidence, final
   score, AE+CSM ownership. Bottom of page: agent's reasoning trace.
4. **Act.**
   - Copy the draft, paste into outbox, send. *Mark Actioned.*
   - Or: useful but not now. *Mark Relevant.*
   - Or: not a fit. *Not Relevant.*
5. **Feedback persists.** Every click writes to `run_log/outcomes.csv`. In
   V1.5 this feeds back into the ranker weights so the agent learns which
   signals actually convert.

---

## 13 · Cost + latency (measured, real run)

V1 run on 117 accounts:

| Metric | Value |
|---|---|
| Steps 1–3 (deterministic) | ~10 seconds |
| Step 4 (context assembly, 44 packets) | < 1 second |
| Step 5 (44 parallel LLM calls, gpt-4o-mini) | ~30 seconds |
| Step 6 + persist | < 1 second |
| **Full pipeline** | **~36 seconds** |
| Tokens per call (avg) | ~2,700 input + ~620 output |
| **Cost per full run** | **~$0.05 on gpt-4o-mini, ~$3-5 on Claude Opus** |

The spec budget is `RUN_COST_CAP_USD=5`. Comfortably under.

---

## 14 · TL;DR

| Decision | How it's made |
|---|---|
| "Should I surface this account?" | DQ1–DQ5 (deterministic rules over typed fields) |
| "Which accounts are most urgent?" | `0.40 × adoption + 0.30 × renewal + 0.30 × log1p(usage)` |
| "Is the gap actually real?" | LLM cross-checks usage + conversations + signals |
| "Who should the rep target?" | LLM picks across SF + Clay pools using title / seniority / buying role / source |
| "Should the AE or CSM drive?" | LLM tags `AE` / `CSM` / `BOTH` based on whether the play is adoption-led or buyer-led |
| "How confident is the agent?" | LLM self-rates on a 0–1 scale; `>0.75` requires gap + persona + ≥2 corroborating signals |
| "Does the rep get a queue?" | Top 5 by `final_score` per AE and per CSM, no low-band signals |
| "What does the rep see?" | Five sections + draft email + audit trail + override feedback buttons |
| "What if an account is dropped?" | Notification fires with rule + explanation + Investigate link |

---

*Companion: [ARCHITECTURE.md](ARCHITECTURE.md) — the system shape, layers,
and V1 → V1.5 migration.*
