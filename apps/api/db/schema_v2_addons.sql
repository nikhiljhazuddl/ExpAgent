-- ═══════════════════════════════════════════════════════════════════════════
-- GTM Mesh IQ — V2 Addons (run AFTER the original schema)
-- Safe to re-run — all CREATE TABLE IF NOT EXISTS
-- ═══════════════════════════════════════════════════════════════════════════

create extension if not exists "pg_trgm";

-- ── 1. CANONICAL ACCOUNTS ────────────────────────────────────────────────────
create table if not exists accounts (
    id              uuid primary key default uuid_generate_v4(),
    name            text not null,
    domain          text,
    email_domain    text,
    sf_id           text unique,
    hubspot_id      text unique,
    industry        text,
    segment         text,
    owner_name      text,
    csm_name        text,
    health_status   text,
    acv             numeric,
    arr             numeric,
    contract_start  date,
    contract_end    date,
    churn_risk      text,
    expansion_candidate boolean default false,
    created_at      timestamptz default now(),
    updated_at      timestamptz default now()
);
create unique index if not exists accounts_domain_idx on accounts(domain) where domain is not null;
create index if not exists accounts_name_trgm  on accounts using gin(name gin_trgm_ops);
create index if not exists accounts_sf_id_idx  on accounts(sf_id);
create index if not exists accounts_hs_id_idx  on accounts(hubspot_id);

-- ── 2. PEOPLE ────────────────────────────────────────────────────────────────
create table if not exists people (
    id                  uuid primary key default uuid_generate_v4(),
    account_id          uuid references accounts(id) on delete set null,
    name                text,
    email               text,
    title               text,
    phone               text,
    linkedin_url        text,
    in_crm              boolean default false,
    source              text,
    sf_contact_id       text unique,
    hubspot_contact_id  text unique,
    raw                 jsonb default '{}',
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);
create index if not exists people_account_id_idx on people(account_id);
create index if not exists people_email_idx      on people(email);

-- ── 3. GONG CALLS ────────────────────────────────────────────────────────────
create table if not exists gong_calls (
    id              text primary key,
    account_id      uuid references accounts(id) on delete set null,
    title           text,
    call_url        text,
    direction       text,
    duration_secs   int,
    started_at      timestamptz,
    speaker_names   text[],
    attendee_emails text[],
    topics          jsonb default '[]',
    highlights      jsonb default '[]',
    action_items    jsonb default '[]',
    key_points      jsonb default '[]',
    trackers_hit    text[],
    raw             jsonb default '{}',
    synced_at       timestamptz default now()
);
create index if not exists gong_calls_account_id_idx on gong_calls(account_id);
create index if not exists gong_calls_started_at_idx on gong_calls(started_at desc);

-- ── 4. FIREFLIES MEETINGS ────────────────────────────────────────────────────
create table if not exists fireflies_meetings (
    id                  text primary key,
    account_id          uuid references accounts(id) on delete set null,
    title               text,
    date                timestamptz,
    duration_secs       int,
    organizer_email     text,
    participant_emails  text[],
    summary             text,
    action_items        jsonb default '[]',
    key_questions       jsonb default '[]',
    outline             jsonb default '[]',
    raw                 jsonb default '{}',
    synced_at           timestamptz default now()
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

-- ── 6. LINEAR ISSUES ─────────────────────────────────────────────────────────
create table if not exists linear_issues (
    id              text primary key,
    account_id      uuid references accounts(id) on delete set null,
    identifier      text,
    title           text,
    status          text,
    priority        int,
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

-- ── 7. HUBSPOT TABLES ────────────────────────────────────────────────────────
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
    hs_id       text primary key,
    account_id  uuid references accounts(id) on delete set null,
    first_name  text,
    last_name   text,
    email       text,
    title       text,
    raw         jsonb default '{}',
    synced_at   timestamptz default now()
);

create table if not exists hubspot_deals (
    hs_id       text primary key,
    account_id  uuid references accounts(id) on delete set null,
    name        text,
    stage       text,
    amount      numeric,
    close_date  date,
    deal_type   text,
    raw         jsonb default '{}',
    synced_at   timestamptz default now()
);

-- ── 8. SALESFORCE — add account_id FK column to existing sf_* tables ─────────
-- (safe: IF NOT EXISTS on column add via DO block)
do $$
begin
    if not exists (
        select 1 from information_schema.columns
        where table_name='sf_accounts' and column_name='account_id'
    ) then
        alter table sf_accounts add column account_id uuid references accounts(id) on delete set null;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_name='sf_opportunities' and column_name='account_id'
    ) then
        alter table sf_opportunities add column account_id uuid references accounts(id) on delete set null;
    end if;

    if not exists (
        select 1 from information_schema.columns
        where table_name='sf_contacts' and column_name='account_id'
    ) then
        alter table sf_contacts add column account_id uuid references accounts(id) on delete set null;
    end if;
end $$;

-- Salesforce full-field raw store (all 300+ fields per object)
create table if not exists sf_accounts_raw (
    sf_id       text primary key,
    account_id  uuid references accounts(id) on delete set null,
    data        jsonb not null,   -- every field Salesforce returns
    synced_at   timestamptz default now()
);

create table if not exists sf_opportunities_raw (
    sf_id       text primary key,
    account_id  uuid references accounts(id) on delete set null,
    data        jsonb not null,
    synced_at   timestamptz default now()
);

create table if not exists sf_contacts_raw (
    sf_id       text primary key,
    account_id  uuid references accounts(id) on delete set null,
    data        jsonb not null,
    synced_at   timestamptz default now()
);

-- ── 9. ACCOUNT 360 VIEW ───────────────────────────────────────────────────────
-- Mapping strategy:
--   • gong/fireflies/pylon/linear/hubspot  → joined by account_id (uuid FK)
--   • signals (old table, text account_id) → joined by account_name OR sf_id text match
-- Everything resolves to the canonical accounts row via domain + name

create or replace view account_360 as
select
    a.id,
    a.name,
    a.domain,
    a.email_domain,
    a.sf_id,
    a.hubspot_id,
    a.segment,
    a.owner_name,
    a.csm_name,
    a.health_status,
    a.acv,
    a.arr,
    a.contract_start,
    a.contract_end,
    a.churn_risk,
    a.expansion_candidate,
    -- counts per source system (all use uuid FK — no type conflict)
    (select count(*) from gong_calls         g  where g.account_id  = a.id) as gong_call_count,
    (select count(*) from fireflies_meetings f  where f.account_id  = a.id) as fireflies_meeting_count,
    (select count(*) from pylon_issues       p  where p.account_id  = a.id) as pylon_issue_count,
    (select count(*) from pylon_issues       p  where p.account_id  = a.id
                                                   and lower(p.status) not in ('resolved','closed')) as pylon_open_issues,
    (select count(*) from linear_issues      l  where l.account_id  = a.id) as linear_issue_count,
    (select count(*) from people             pe where pe.account_id = a.id) as contact_count,
    (select count(*) from hubspot_deals      hd where hd.account_id = a.id) as hubspot_deal_count,
    -- latest timestamps
    (select max(g.started_at) from gong_calls         g where g.account_id = a.id) as last_gong_call,
    (select max(f.date)       from fireflies_meetings f where f.account_id = a.id) as last_meeting,
    (select max(p.created_at) from pylon_issues       p where p.account_id = a.id) as last_support_ticket,
    -- signals: old table uses text account_name, match by name (case-insensitive) or sf_id
    (select count(*) from signals s
       where lower(s.account_name) = lower(a.name)
          or (a.sf_id is not null and s.account_id = a.sf_id)
    ) as signal_count
from accounts a;
