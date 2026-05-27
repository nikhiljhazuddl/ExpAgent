-- ═══════════════════════════════════════════════════════════════════════════
-- GTM Mesh IQ — Unified Revenue Data Warehouse
-- Run once in: Supabase Dashboard → SQL Editor → New Query
-- ═══════════════════════════════════════════════════════════════════════════

create extension if not exists "uuid-ossp";
create extension if not exists "pg_trgm";   -- fuzzy name matching

-- ── 1. CANONICAL ACCOUNTS ────────────────────────────────────────────────────
-- Single source of truth. Every record in every other table points here.
-- Matching keys: domain (primary), name (secondary), email_domain (tertiary)

create table if not exists accounts (
    id              uuid primary key default uuid_generate_v4(),
    name            text not null,
    domain          text,                   -- normalised: crowdstrike.com
    email_domain    text,                   -- from contact emails
    -- CRM cross-refs
    sf_id           text unique,
    hubspot_id      text unique,
    -- enriched fields (from CSV / SF)
    industry        text,
    segment         text,                   -- Strategic / Enterprise / Mid-Market
    owner_name      text,                   -- AE
    csm_name        text,
    health_status   text,
    acv             numeric,
    arr             numeric,
    contract_start  date,
    contract_end    date,
    churn_risk      text,
    expansion_candidate boolean default false,
    -- bookkeeping
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

create unique index if not exists accounts_domain_idx  on accounts(domain) where domain is not null;
create index        if not exists accounts_name_trgm   on accounts using gin(name gin_trgm_ops);
create index        if not exists accounts_sf_id_idx   on accounts(sf_id);
create index        if not exists accounts_hs_id_idx   on accounts(hubspot_id);

-- ── 2. PEOPLE ────────────────────────────────────────────────────────────────
-- Contacts from all sources — CSV, SF, HubSpot, Gong participants, outside CRM

create table if not exists people (
    id              uuid primary key default uuid_generate_v4(),
    account_id      uuid references accounts(id) on delete set null,
    name            text,
    email           text,
    title           text,
    phone           text,
    linkedin_url    text,
    -- source flags
    in_crm          boolean default false,
    source          text,           -- 'csv' | 'salesforce' | 'hubspot' | 'gong' | 'fireflies' | 'manual'
    sf_contact_id   text unique,
    hubspot_contact_id text unique,
    -- bookkeeping
    raw             jsonb default '{}',
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);

create index if not exists people_account_id_idx on people(account_id);
create index if not exists people_email_idx      on people(email);
create index if not exists people_name_trgm      on people using gin(name gin_trgm_ops);

-- ── 3. GONG CALLS ────────────────────────────────────────────────────────────

create table if not exists gong_calls (
    id              text primary key,       -- Gong call ID
    account_id      uuid references accounts(id) on delete set null,
    title           text,
    call_url        text,
    direction       text,                   -- Inbound / Outbound
    duration_secs   int,
    started_at      timestamptz,
    -- people
    speaker_names   text[],
    attendee_emails text[],
    -- AI insights
    topics          jsonb default '[]',
    highlights      jsonb default '[]',
    action_items    jsonb default '[]',
    key_points      jsonb default '[]',
    trackers_hit    text[],
    -- raw
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

create index if not exists gong_calls_account_id_idx on gong_calls(account_id);
create index if not exists gong_calls_started_at_idx on gong_calls(started_at desc);

-- ── 4. FIREFLIES MEETINGS ────────────────────────────────────────────────────

create table if not exists fireflies_meetings (
    id              text primary key,       -- Fireflies transcript ID
    account_id      uuid references accounts(id) on delete set null,
    title           text,
    date            timestamptz,
    duration_secs   int,
    organizer_email text,
    participant_emails text[],
    -- AI outputs
    summary         text,
    action_items    jsonb default '[]',
    key_questions   jsonb default '[]',
    outline         jsonb default '[]',
    -- raw
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

create index if not exists fireflies_account_id_idx on fireflies_meetings(account_id);
create index if not exists fireflies_date_idx       on fireflies_meetings(date desc);

-- ── 5. PYLON ISSUES ──────────────────────────────────────────────────────────

create table if not exists pylon_issues (
    id              text primary key,
    account_id      uuid references accounts(id) on delete set null,
    title           text,
    status          text,
    priority        text,
    category        text,
    assignee_name   text,
    reporter_email  text,
    created_at      timestamptz,
    resolved_at     timestamptz,
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

create index if not exists pylon_account_id_idx on pylon_issues(account_id);
create index if not exists pylon_status_idx     on pylon_issues(status);

-- ── 6. LINEAR ISSUES ─────────────────────────────────────────────────────────

create table if not exists linear_issues (
    id              text primary key,
    account_id      uuid references accounts(id) on delete set null,
    identifier      text,                   -- e.g. ENG-123
    title           text,
    status          text,
    priority        int,                    -- 0=none,1=urgent,2=high,3=medium,4=low
    assignee_name   text,
    team_name       text,
    labels          text[],
    due_date        date,
    created_at      timestamptz,
    completed_at    timestamptz,
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

create index if not exists linear_account_id_idx on linear_issues(account_id);
create index if not exists linear_status_idx     on linear_issues(status);

-- ── 7. HUBSPOT RAW ───────────────────────────────────────────────────────────

create table if not exists hubspot_companies (
    hs_id           text primary key,
    account_id      uuid references accounts(id) on delete set null,
    name            text,
    domain          text,
    industry        text,
    arr             numeric,
    lifecycle_stage text,
    owner_name      text,
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

create table if not exists hubspot_contacts (
    hs_id           text primary key,
    account_id      uuid references accounts(id) on delete set null,
    first_name      text,
    last_name       text,
    email           text,
    title           text,
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

create table if not exists hubspot_deals (
    hs_id           text primary key,
    account_id      uuid references accounts(id) on delete set null,
    name            text,
    stage           text,
    amount          numeric,
    close_date      date,
    deal_type       text,
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

-- ── 8. SALESFORCE RAW ────────────────────────────────────────────────────────

create table if not exists sf_accounts (
    sf_id               text primary key,
    account_id          uuid references accounts(id) on delete set null,
    name                text,
    industry            text,
    annual_revenue      numeric,
    number_of_employees int,
    owner_name          text,
    csm_name            text,
    arr                 numeric,
    contract_end_date   date,
    health_score        text,
    raw                 jsonb default '{}',
    synced_at           timestamptz default now()
);

create table if not exists sf_opportunities (
    sf_id               text primary key,
    account_sf_id       text references sf_accounts(sf_id) on delete cascade,
    account_id          uuid references accounts(id) on delete set null,
    name                text,
    stage               text,
    amount              numeric,
    close_date          date,
    type                text,
    raw                 jsonb default '{}',
    synced_at           timestamptz default now()
);

create table if not exists sf_contacts (
    sf_id           text primary key,
    account_sf_id   text references sf_accounts(sf_id) on delete cascade,
    account_id      uuid references accounts(id) on delete set null,
    first_name      text,
    last_name       text,
    title           text,
    email           text,
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);

-- ── 9. EXPANSION AGENT OUTPUT ────────────────────────────────────────────────

create table if not exists signals (
    id              text primary key,
    run_id          text,
    account_id      uuid references accounts(id) on delete set null,
    account_name    text,
    signal_type     text,
    priority        text,
    owner_role      text,
    owner_name      text,
    headline        text,
    rationale       text,
    recommended_action text,
    evidence        jsonb default '[]',
    metadata        jsonb default '{}',
    created_at      timestamptz default now()
);

create index if not exists signals_run_id_idx     on signals(run_id);
create index if not exists signals_account_id_idx on signals(account_id);
create index if not exists signals_owner_name_idx on signals(owner_name);

create table if not exists notifications (
    id                  uuid primary key default uuid_generate_v4(),
    run_id              text,
    account_id          uuid references accounts(id) on delete set null,
    account_name        text,
    disqualifier_rule   text,
    owner_role          text,
    owner_name          text,
    message             text,
    metadata            jsonb default '{}',
    created_at          timestamptz default now()
);

create table if not exists runs (
    id              text primary key,
    status          text,
    started_at      timestamptz,
    finished_at     timestamptz,
    accounts_total  int default 0,
    accounts_ok     int default 0,
    signals_kept    int default 0,
    cost_usd        numeric(10,4) default 0,
    metadata        jsonb default '{}',
    created_at      timestamptz default now()
);

create table if not exists feedback (
    id          uuid primary key default uuid_generate_v4(),
    signal_id   text references signals(id) on delete set null,
    run_id      text,
    username    text,
    role        text,
    relevant    boolean,
    actioned    boolean,
    notes       text default '',
    created_at  timestamptz default now()
);

create table if not exists account_contexts (
    account_id  text primary key,
    run_id      text,
    data        jsonb not null,
    updated_at  timestamptz default now()
);

-- ── 10. ACCOUNT 360 VIEW ─────────────────────────────────────────────────────
-- Single query gives you everything tied to an account

create or replace view account_360 as
select
    a.id,
    a.name,
    a.domain,
    a.segment,
    a.owner_name,
    a.csm_name,
    a.health_status,
    a.acv,
    a.arr,
    a.contract_end,
    a.churn_risk,
    a.expansion_candidate,
    -- counts from each system
    (select count(*) from gong_calls      g where g.account_id = a.id) as gong_call_count,
    (select count(*) from fireflies_meetings f where f.account_id = a.id) as fireflies_meeting_count,
    (select count(*) from pylon_issues    p where p.account_id = a.id) as pylon_issue_count,
    (select count(*) from pylon_issues    p where p.account_id = a.id and p.status != 'resolved') as pylon_open_issues,
    (select count(*) from linear_issues   l where l.account_id = a.id) as linear_issue_count,
    (select count(*) from people          pe where pe.account_id = a.id) as contact_count,
    (select count(*) from hubspot_deals   hd where hd.account_id = a.id) as open_deals,
    -- latest activity timestamps
    (select max(g.started_at) from gong_calls g where g.account_id = a.id) as last_gong_call,
    (select max(f.date) from fireflies_meetings f where f.account_id = a.id) as last_meeting,
    (select max(p.created_at) from pylon_issues p where p.account_id = a.id) as last_support_ticket,
    -- signals
    (select count(*) from signals s where s.account_id = a.id) as signal_count
from accounts a;
