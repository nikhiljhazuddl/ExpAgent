"""Builds an AccountContext (Claude input) from a ranked AccountNode.

Cap to ~6,000 input tokens. Pruning order if oversize:
    1) drop conversation transcripts (keep summaries only)
    2) trim contact lists (keep top by persona_fit_score / first 8)
    3) drop signal arrays (gong_key_points, fireflies_action_items, topics)

V1.5-style enrichment: if an AccountAgent is supplied, append its historical
trend + feedback memory as data_quality_flags so the reasoning agent can
account for "the AE marked the last 3 signals not relevant" or "this account's
adoption health has been Yellow for 4 consecutive runs".
"""

from __future__ import annotations

import json
from datetime import date
from typing import Optional

from schemas.account_context import (
    AccountContext,
    AccountProfile,
    ClayContactCtx,
    ContactCtx,
    ConversationsCtx,
    CurrentState,
    IcpPopulationCtx,
    OwnerRef,
    OwnershipCtx,
    Signals1PCtx,
    Signals2PCtx,
    Signals3PCtx,
    UsageCtx,
)
from schemas.account_node import AccountNode

# Approximation: ~4 chars per token (English). 6000 tokens ≈ 24_000 chars.
TOKEN_CAP = 6000
CHAR_CAP = TOKEN_CAP * 4


def _renewal_days(node: AccountNode, today: date) -> Optional[int]:
    target = node.plan_end_date or node.latest_expansion_contract_end
    if target is None:
        return None
    return (target - today).days


def _last_activity_days(node: AccountNode, today: date) -> Optional[int]:
    if node.last_activity_date is None:
        return None
    return (today - node.last_activity_date).days


def _active_use_cases_from_usage(node: AccountNode) -> list[str]:
    """Approximate the 'active in prod' list from non-zero usage counts."""
    pairs = [
        ("Field Events", node.usage.field_events_all_time),
        ("Third-Party Events", node.usage.third_party_events_all_time),
        ("Webinars", node.usage.webinars_all_time),
        ("Standard In-Person", node.usage.standard_in_person),
        ("Standard Hybrid", node.usage.standard_hybrid),
        ("Standard Virtual", node.usage.standard_virtual),
        ("Conferences", node.usage.conferences_all_time),
    ]
    return [label for label, count in pairs if count > 0]


def _contact_to_ctx(c) -> ContactCtx:
    return ContactCtx(
        name=c.name,
        title=c.title,
        seniority=c.seniority,
        persona=c.persona,
        persona_fit_score=c.persona_fit_score,
        linkedin=c.linkedin,
        email=c.email,
    )


def _clay_to_ctx(c) -> ClayContactCtx:
    return ClayContactCtx(
        name=c.name,
        title=c.title,
        linkedin=c.linkedin,
        email=c.email,
        tagged_use_case=c.tagged_use_case,
        found_in_prod=c.found_in_prod,
    )


def build_context(
    node: AccountNode, priority_score: float, today: date
) -> AccountContext:
    """Build the Claude-facing context. Always returns within the token cap."""

    # Sort SF contacts by persona_fit_score desc so prune keeps the strongest.
    sf_sorted = sorted(
        node.contacts_in_product_sf,
        key=lambda c: (c.persona_fit_score or 0.0),
        reverse=True,
    )
    contacts_sf = [_contact_to_ctx(c) for c in sf_sorted]
    contacts_clay = [_clay_to_ctx(c) for c in node.contacts_not_in_product_clay]

    ctx = AccountContext(
        account_id=node.account_id_15,
        account_name=node.account_name,
        domain=node.domain,
        ownership=OwnershipCtx(
            ae=OwnerRef(name=node.ownership.ae_name, role=node.ownership.ae_role),
            csm=OwnerRef(name=node.ownership.csm_name),
        ),
        segment=node.segment,
        acv_usd=node.acv_usd,
        current_state=CurrentState(
            adoption_health=node.adoption_health,
            active_use_cases_in_prod=_active_use_cases_from_usage(node),
            use_case_gap_field=node.use_case_gap_field,
            renewal_proximity_days=_renewal_days(node, today),
            is_active_customer=node.is_active_customer,
            has_open_expansion_opp=node.has_open_expansion_opp,
            last_activity_days_ago=_last_activity_days(node, today),
        ),
        usage=UsageCtx(
            field_events_all_time=node.usage.field_events_all_time,
            third_party_events_all_time=node.usage.third_party_events_all_time,
            webinars_all_time=node.usage.webinars_all_time,
            standard_in_person=node.usage.standard_in_person,
            standard_hybrid=node.usage.standard_hybrid,
            standard_virtual=node.usage.standard_virtual,
            conferences_all_time=node.usage.conferences_all_time,
            total_events_all_time=node.usage.total,
        ),
        account_profile=AccountProfile(
            target_departments=node.target_departments,
            sales_model=node.sales_model,
            target_customers=node.target_customers,
        ),
        signals_1p=Signals1PCtx(
            factors_intent_label=node.signals_1p.factors_intent_label,
            demo_pricing_visits_90d=node.signals_1p.demo_pricing_visits_90d,
            factors_last_intent_date=node.signals_1p.factors_last_intent_date,
        ),
        signals_2p=Signals2PCtx(
            linkedin_engagement_30d=node.signals_2p.linkedin_engagement_30d,
            zuddl_mentions=node.signals_2p.zuddl_mentions,
            champion_job_moves_90d=node.signals_2p.champion_job_moves_90d,
        ),
        signals_3p=Signals3PCtx(
            event_role_hiring_90d=node.signals_3p.event_role_hiring_90d,
            competitor_mentions_g2_90d=node.signals_3p.competitor_mentions_g2_90d,
            competitor_in_stack=node.signals_3p.competitor_in_stack,
        ),
        icp_population=IcpPopulationCtx(
            conferences_icp_count=node.icp_population.conferences_icp_count,
            field_events_icp_count=node.icp_population.field_events_icp_count,
            webinar_icp_count=node.icp_population.webinar_icp_count,
            third_party_icp_count=node.icp_population.third_party_icp_count,
        ),
        conversations=ConversationsCtx(
            has_gong=node.conversations.has_gong,
            has_fireflies=node.conversations.has_fireflies,
            total_calls=node.conversations.total_calls,
            date_range=node.conversations.date_range,
            gong_business_summary=node.conversations.gong_business_summary,
            gong_product_interests=node.conversations.gong_product_interests,
            gong_competitors_mentioned=node.conversations.gong_competitors_mentioned,
            gong_key_points=node.conversations.gong_key_points,
            fireflies_overview=node.conversations.fireflies_overview,
            fireflies_action_items=node.conversations.fireflies_action_items,
            fireflies_topics=node.conversations.fireflies_topics,
        ),
        contacts_in_product_sf=contacts_sf,
        contacts_not_in_product_clay=contacts_clay,
        deterministic_priority_score=priority_score,
        data_quality_flags=list(node.data_quality_flags),
    )

    return _prune_to_cap(ctx)


def _size_chars(ctx: AccountContext) -> int:
    return len(ctx.model_dump_json())


def _prune_to_cap(ctx: AccountContext) -> AccountContext:
    """Apply the spec's prune order until under CHAR_CAP."""
    if _size_chars(ctx) <= CHAR_CAP:
        return ctx

    # 1) Drop transcripts: keep only summary + product_interests / topics.
    ctx.conversations.gong_key_points = []
    ctx.conversations.fireflies_action_items = []
    if _size_chars(ctx) <= CHAR_CAP:
        return ctx

    # 2) Trim contact lists.
    ctx.contacts_in_product_sf = ctx.contacts_in_product_sf[:8]
    ctx.contacts_not_in_product_clay = ctx.contacts_not_in_product_clay[:8]
    if _size_chars(ctx) <= CHAR_CAP:
        return ctx

    # 3) Drop signal arrays.
    ctx.conversations.gong_product_interests = ctx.conversations.gong_product_interests[:5]
    ctx.conversations.gong_competitors_mentioned = ctx.conversations.gong_competitors_mentioned[:5]
    ctx.conversations.fireflies_topics = ctx.conversations.fireflies_topics[:5]
    ctx.signals_3p.competitor_in_stack = ctx.signals_3p.competitor_in_stack[:5]

    # 4) Last resort: truncate long summaries.
    if ctx.conversations.gong_business_summary and _size_chars(ctx) > CHAR_CAP:
        ctx.conversations.gong_business_summary = ctx.conversations.gong_business_summary[:1500]
    if ctx.conversations.fireflies_overview and _size_chars(ctx) > CHAR_CAP:
        ctx.conversations.fireflies_overview = ctx.conversations.fireflies_overview[:1500]

    return ctx
