"""AccountContext — input to the reasoning agent.

This is the Claude-facing shape. Built by context_builder.py from an AccountNode.
Capped to ~6000 input tokens. Pruning order: transcripts → contact lists → signal arrays.
Schema mirrors §5 of the build spec.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class OwnerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    role: Optional[str] = None


class OwnershipCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ae: OwnerRef = Field(default_factory=OwnerRef)
    csm: OwnerRef = Field(default_factory=OwnerRef)


class CurrentState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adoption_health: Optional[str] = None
    active_use_cases_in_prod: list[str] = Field(default_factory=list)
    use_case_gap_field: Optional[str] = None
    renewal_proximity_days: Optional[int] = None
    is_active_customer: bool = True
    has_open_expansion_opp: bool = False
    last_activity_days_ago: Optional[int] = None


class UsageCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_events_all_time: float = 0.0
    third_party_events_all_time: float = 0.0
    webinars_all_time: float = 0.0
    standard_in_person: float = 0.0
    standard_hybrid: float = 0.0
    standard_virtual: float = 0.0
    conferences_all_time: float = 0.0
    total_events_all_time: float = 0.0


class AccountProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_departments: list[str] = Field(default_factory=list)
    sales_model: Optional[str] = None
    target_customers: list[str] = Field(default_factory=list)


class Signals1PCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factors_intent_label: Optional[str] = None
    demo_pricing_visits_90d: Optional[int] = None
    factors_last_intent_date: Optional[str] = None


class Signals2PCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin_engagement_30d: Optional[int] = None
    zuddl_mentions: Optional[bool] = None
    champion_job_moves_90d: Optional[int] = None


class Signals3PCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_role_hiring_90d: Optional[int] = None
    competitor_mentions_g2_90d: Optional[int] = None
    competitor_in_stack: list[str] = Field(default_factory=list)


class IcpPopulationCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conferences_icp_count: int = 0
    field_events_icp_count: int = 0
    webinar_icp_count: int = 0
    third_party_icp_count: int = 0


class ConversationsCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    has_gong: bool = False
    has_fireflies: bool = False
    total_calls: int = 0
    date_range: Optional[str] = None
    gong_business_summary: Optional[str] = None
    gong_product_interests: list[str] = Field(default_factory=list)
    gong_competitors_mentioned: list[str] = Field(default_factory=list)
    gong_key_points: list[str] = Field(default_factory=list)
    fireflies_overview: Optional[str] = None
    fireflies_action_items: list[str] = Field(default_factory=list)
    fireflies_topics: list[str] = Field(default_factory=list)


class ContactCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    title: Optional[str] = None
    seniority: Optional[str] = None
    persona: Optional[str] = None
    persona_fit_score: Optional[float] = None
    linkedin: Optional[str] = None
    email: Optional[str] = None


class ClayContactCtx(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    title: Optional[str] = None
    linkedin: Optional[str] = None
    email: Optional[str] = None
    tagged_use_case: Optional[str] = None
    found_in_prod: bool = False


class AccountContext(BaseModel):
    """Input to Claude. ~6000 tokens cap."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    account_name: str
    domain: Optional[str] = None
    ownership: OwnershipCtx = Field(default_factory=OwnershipCtx)
    segment: Optional[str] = None
    acv_usd: Optional[float] = None

    current_state: CurrentState = Field(default_factory=CurrentState)
    usage: UsageCtx = Field(default_factory=UsageCtx)
    account_profile: AccountProfile = Field(default_factory=AccountProfile)

    signals_1p: Signals1PCtx = Field(default_factory=Signals1PCtx)
    signals_2p: Signals2PCtx = Field(default_factory=Signals2PCtx)
    signals_3p: Signals3PCtx = Field(default_factory=Signals3PCtx)
    icp_population: IcpPopulationCtx = Field(default_factory=IcpPopulationCtx)

    conversations: ConversationsCtx = Field(default_factory=ConversationsCtx)

    contacts_in_product_sf: list[ContactCtx] = Field(default_factory=list)
    contacts_not_in_product_clay: list[ClayContactCtx] = Field(default_factory=list)

    deterministic_priority_score: float = 0.0
    data_quality_flags: list[str] = Field(default_factory=list)
