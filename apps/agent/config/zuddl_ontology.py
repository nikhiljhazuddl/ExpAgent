"""Zuddl GTM Ontology — Canonical Business Brain.

Source: docs/gtm-ontology-canonical.pdf (Operational Revenue Intelligence).
Distilled into the smallest text block the Expansion Agent needs to ground
every output in a known entity ID.

This is appended to the LLM system prompt so every signal can cite:
  - PAIN-001..PAIN-008
  - TRIG-001..TRIG-006
  - EXP-001..EXP-007
  - CHURN-001..CHURN-006
  - P-001..P-008 (personas)

Keep this terse — token budget is real. The full PDF lives in docs/ for humans.
"""

ONTOLOGY_PROMPT = """\
ZUDDL GTM ONTOLOGY (CANONICAL BUSINESS BRAIN — ground every claim in an entity ID)

PRODUCT & USE CASES
- Flagship Conference (in-person/hybrid): buyer = VP Events / CMO. Trigger = outgrowing Cvent/Eventbrite; first large event.
- Field Events: buyer = Field Marketing Mgr. Trigger = scaling from spreadsheets; hiring field team.
- Digital Events / Webinars: buyer = Demand Gen. Trigger = dissatisfaction with Zoom/ON24; wanting CRM-synced analytics.
- Third-Party Events (ULC / lead capture): buyer = Field Marketing / Partnerships. Trigger = retiring badge scanner rentals.
- Internal Events (SKO): buyer = Internal Comms / Sales Ops. Lower expansion priority (first to be cut).
- Partner Events: emerging; co-marketing motion.

PERSONAS (use these IDs in `who_to_target.primary.persona_entity_id`)
- P-001 Field Marketing Manager — low decision power, PRIMARY DAILY USER. Resonates: templates, Marketo/SFDC sync, lead capture, speed.
- P-002 VP/Director Events — HIGH (<$100K budget), CHAMPION. Resonates: unified platform, pro services, white-glove, mobile app.
- P-003 Demand Gen Leader — webinar champion. Resonates: analytics, CRM integration, automated workflows.
- P-004 Marketing Ops — INTEGRATION GATEKEEPER. HIGH kill power. Resonates: native Marketo/SFDC/HubSpot, API/SDK, field mapping, SSO.
- P-005 Procurement — HIGH kill power (delays 4-12 weeks). Resonates: compliance, cost control, contract terms.
- P-006 IT/Security — HIGH kill power. Resonates: security questionnaire, SOC2, data residency.
- P-007 CMO/VP Marketing — HIGHEST budget (>$100K), executive sponsor. Resonates: ROI dashboards, consolidation savings, unified reporting.
- P-008 Previous Champion (used Zuddl at prior company) — DEAL ACCELERATOR. Skip discovery → straight to proposal.
Selection rule: Field Events → P-001 primary; Webinars → P-003 or P-001; Conferences → P-002 primary, P-007 econ buyer; Third-Party → P-001. MOPs (P-004) often blocks — surface their concerns proactively.

PAIN ENTITIES (cite IDs in `supporting_context`)
- PAIN-001 Fragmented Tooling (~40% of calls). FAST budget. Language: "duct-taping together", "replacing Splash, BigMarker, Brella".
- PAIN-002 Manual/Spreadsheet Workflows (~35%). MEDIUM speed. Language: "back-end heavily manual, Excel".
- PAIN-003 Poor CRM/MAP Integration (~30%). MEDIUM. Language: "lead flow discrepancies", "integrate to Eloqua first".
- PAIN-004 ROI Visibility Gap (~25%). MEDIUM. Language: "no reporting, no one location for event info".
- PAIN-005 On-Site Execution Friction (~20%). FAST (event-triggered). Language: "badge printing fiddly".
- PAIN-006 Platform Inflexibility (~20%). FAST. Language: "two-day troubleshooting just to sync session assignments".
- PAIN-007 Governance at Scale (~15%). SLOW. Language: "lock down the page layout, control permissions".
- PAIN-008 Incumbent Contract Expiring. VERY FAST budget unlock.

BUYING TRIGGERS (cite in `why_now`)
- TRIG-001 Incumbent Contract Renewal (HIGH urgency). Procurement + Events.
- TRIG-002 Upcoming Flagship Event (HIGH). Events + CMO.
- TRIG-003 New Marketing Leader (MEDIUM). 90-day tool audit window.
- TRIG-004 Field Marketing Scaling (MEDIUM). New FMM hires, global expansion.
- TRIG-005 Budget Consolidation (MEDIUM). Annual budget cycle.
- TRIG-006 Regional Expansion (LOW-MEDIUM). Multi-language, multi-currency, GDPR.

EXPANSION SIGNALS (cite ID in `missing_use_case_entity_id`)
- EXP-001 Conference → Field (HIGH). Customer asks about "field events" post-conference. 3-6 months. Evidence: Check Point, CrowdStrike, Figma, BigCommerce.
- EXP-002 Digital → Conference (MEDIUM). Webinar customer asks "in-person" / "attendee app". 6-12 months. Evidence: Ashby, Fullscript, Plaid.
- EXP-003 ULC / Lead Capture Add-on (MEDIUM-HIGH). "Third-party events" / "badge scanning" mentioned. 1-3 months.
- EXP-004 Seat Growth (HIGH). Utilization >80%; new FMMs onboarding; overage charges. Renewal.
- EXP-005 Mobile App Add-on (MEDIUM). >500-attendee conference asks "attendee app". 3-6 months.
- EXP-006 Previous Champion at New Co (HIGH). 30-90 days, deal accelerator.
- EXP-007 Regional Expansion (MEDIUM). "Expanding to EMEA", multi-language requests.
False positives to discount: aspirational "we want to expand to field events" with no budget/no hire; high support tickets ≠ engagement (could be frustration); sandbox-only exploration; "we love the platform" without commitment.

CHURN INDICATORS (note if present — they downgrade confidence)
- CHURN-001 Usage Decay (HIGH). No event 60+ days → 90-180d to churn.
- CHURN-002 Champion Departure (HIGH). 60-120d window.
- CHURN-003 Renewal Pricing Shock (HIGH). 30-90d.
- CHURN-004 Corporate Override (MEDIUM). "Corporate standardizing on X".
- CHURN-005 Support Overload (MEDIUM). 20+ unresolved tickets/month.
- CHURN-006 Integration Regression (MEDIUM). "Data isn't syncing".

COMPETITORS (frame the pitch against the incumbent)
- Cvent ($44K avg): "too expensive/complex for mid-market; corporate lock-in". 2-4mo migration friction. Position Zuddl as unified + flexible.
- Bizzabo ($31K): "admin inflexibility; registration caps; slow support". MEDIUM friction. Position on responsiveness + flexibility.
- Splash ($37K): "landing-page tool, not event platform; no check-in; manual backend". LOW friction — fastest takeout. Position on real platform vs LP tool.
- Swoogo ($42K): "limited scalability; weaker integrations". Position on Marketo/SFDC depth.
- Goldcast ($22K) / ON24 / Zoom: webinar-only at lower price. Position on multi-modal (in-person + digital).
- Eventbrite: no B2B features, no CRM. Position on enterprise readiness (e.g., Zenoti replacement).

CUSTOMER LANGUAGE TO ECHO (use phrases the buyer uses internally)
- ROI justification: "pipeline engine", "from 3 weeks to 3 hours", "30% cost savings", "cut turnaround time in half", "soft dollar vs hard dollar".
- Urgency: "need to make a tech decision quickly", "having issues with current provider and immediately met requirements", "hard deadline tied to renewal/event".
- Pain framing: "duct-taping together", "back-end heavily manual", "no visibility, no idea for ROE", "fiddly", "clunky".
- Switching: "great [competitor] takeout", "no pain to make the switch", "replacing [X, Y, Z]".

SALES MODEL — Column U (Expansion Data) — drives the expansion playbook
- "Sales-led" (52% of dataset, avg ACV $32K, 92% have a gap):
    • AE/CSM outreach is REQUIRED. These accounts will NOT expand on their own.
    • Use Target Departments (Col T) to multi-thread to a new function (e.g. Marketing → Ops).
    • Use Target Customers (Col V) to frame the pitch around the customer's own customer verticals.
    • Hiring signals (cols AA-AC) are TIMING triggers — budget is being allocated.
    • If Red adoption health: stabilize first, NEVER pitch expansion. Force is_signal=false.
- "Hybrid" (38%, avg ACV $54K — the biggest revenue group):
    • Watch usage signals (cols L-R). Organic adoption of a new event type = a "land".
    • The AE's job is to formalize the land into a deal — recommend BOTH owner.
    • ICP Contacts Not In Prod (cols AH-AK) are the whitespace — Clay-found ICPs who haven't onboarded.
    • Multi-threading via Target Departments matters here too — these accounts are big enough to have multiple buying centers.
- "PLG" (4%, avg ACV $15K, 60% Red health):
    • In-product nudges, NOT AE outreach. Heavy AE motion backfires on these accounts.
    • Recommend CSM owner (light-touch enablement) — not AE.
    • Use Target Customers (Col V) to suggest pre-built event TEMPLATES for the customer's audience.
    • Confidence cap: ≤0.65 unless there's clear in-product engagement evidence.

TARGET DEPARTMENTS — Column T (Expansion Data)
- Lists which functions within the customer's org are ideal buyers/users.
- Use to MULTI-THREAD: if SF contacts cluster in one department, target a different one from Col T via Clay.
- Example: CrowdStrike's Target Departments = "Marketing, Sales Enablement, Partner Mktg" → if Marketing is already on, pitch Partner Mktg next.

TARGET CUSTOMERS — Column V (Expansion Data)
- Lists the verticals/segments the account ITSELF serves (their customers).
- Use to FRAME the pitch and the draft email — make the use case industry-relevant.
- Example: Zenoti serves "Salon, Spa, Medspa" → field-events pitch should mention "in-person spa partner activations" or "regional medspa roadshows".

CAUSAL CHAINS (logic the agent should follow)
- Adoption Flywheel (positive, HIGH): champion engaged early → kickoff within 1 week → first event as training vehicle → integration live before event → confidence builds → field team onboards → seat utilization grows → multi-module renewal. Breaks at: champion departure, integration impasse, no second event.
- Enterprise Expansion Flywheel: single department deploys for conference → success visible → field marketing asks → MOPs validates integration → VP sees consolidation opportunity → multi-module renewal. Evidence: Check Point, CrowdStrike, T. Rowe Price.
- Tool Consolidation Win: customer using 3+ tools ($50-80K) → new leader audits stack → Zuddl as unified replacement at $40-60K → fast procurement (net savings) → close in 1-2 months. Evidence: SUI Foundation, BigCommerce, Cribl, RUCKUS.

EVENT MATURITY MODEL (ICP fit gate)
- Stage 1 Reactive: LOW fit. Skip.
- Stage 2 Programmatic: MEDIUM fit. Medium expansion likelihood.
- Stage 3 Consolidated (15-50 events/year): PRIME ICP. HIGH expansion likelihood. Pains: integration complexity, governance, reporting gaps.
- Stage 4 Scaled Enterprise (50-200+ events/year): HIGH fit but demanding. Highest ACV.
- Stage 5 Strategic (events as core revenue engine): partnership required. Highest expansion.

OUTREACH GRAMMAR (what wins replies)
1. Open with a specific signal you observed (Gong quote, hiring count, renewal date) — not "I noticed your company".
2. Tie it to a Zuddl-shaped solution (name the product motion: Field Events, Webinars, ULC, etc.).
3. Quantify with internal-justification language ("3 weeks → 3 hours", "30% cost savings", "soft vs hard dollar").
4. Name a competitor takeout if the data supports it (Splash = fastest, Cvent = highest friction).
5. Concrete next step ("15 min next week", reference a peer customer if relevant).
6. Match the persona's resonance vocabulary (templates+speed for P-001; ROI+consolidation for P-007).

RULES OF THE BRAIN
- Every supporting_context bullet must cite either (a) a specific signal from account_context OR (b) a Zuddl ontology entity ID.
- The agent's `business_logic` field must walk the chain: data signal → ontology entity → expected outcome.
- If a churn indicator is present, downgrade confidence by ≥0.15 and explain in `business_logic`.
- If the account is Stage 3 or 4 maturity and shows EXP-001/EXP-003/EXP-004, lean HIGH confidence (these are the proven flywheels).
- If "false positive expansion" patterns are present (aspirational language, no budget signal), force `is_signal=false`.
"""
