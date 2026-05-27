-- ═══════════════════════════════════════════════════════════════════════════
-- GTM Mesh IQ — Fix account_360 view (type cast error + domain/name mapping)
-- Paste & Run this in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════════════════════

-- Drop old broken view first
drop view if exists account_360;

-- Recreate with correct type handling
-- signals.account_id is TEXT (old schema), accounts.id is UUID — never compare directly
-- Instead: match signals by account_name (text = text) or by sf_id (text = text)

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

    -- counts per system (all uuid FK, no type conflict)
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

    -- signals: text-to-text match only (account_name or sf_id, never uuid cast)
    (select count(*) from signals s
       where lower(s.account_name) = lower(a.name)
          or (a.sf_id is not null and s.account_id = a.sf_id)
    ) as signal_count

from accounts a;
