"""AccountNode — the joined per-account record built by repository.py.

Lives in memory in V1. In V1.5 this maps to the `account_snapshots` + `accounts`
tables in Postgres. Keep field names stable: the persistence layer relies on them.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Ownership(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ae_name: Optional[str] = None
    ae_role: Optional[str] = None
    csm_name: Optional[str] = None
    csm_missing: bool = False


class UsageCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_events_all_time: float = 0.0
    third_party_events_all_time: float = 0.0
    webinars_all_time: float = 0.0
    standard_in_person: float = 0.0
    standard_hybrid: float = 0.0
    standard_virtual: float = 0.0
    conferences_all_time: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.field_events_all_time
            + self.third_party_events_all_time
            + self.webinars_all_time
            + self.standard_in_person
            + self.standard_hybrid
            + self.standard_virtual
            + self.conferences_all_time
        )


class Signals1P(BaseModel):
    model_config = ConfigDict(extra="forbid")
    factors_intent_label: Optional[str] = None
    demo_pricing_visits_90d: Optional[int] = None
    factors_last_intent_date: Optional[str] = None


class Signals2P(BaseModel):
    model_config = ConfigDict(extra="forbid")
    linkedin_engagement_30d: Optional[int] = None
    zuddl_mentions: Optional[bool] = None
    champion_job_moves_90d: Optional[int] = None


class Signals3P(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_role_hiring_90d: Optional[int] = None
    competitor_mentions_g2_90d: Optional[int] = None
    competitor_in_stack: list[str] = Field(default_factory=list)


class IcpPopulation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    conferences_icp_count: int = 0
    field_events_icp_count: int = 0
    webinar_icp_count: int = 0
    third_party_icp_count: int = 0


class Conversations(BaseModel):
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


class Contact(BaseModel):
    model_config = ConfigDict(extra="allow")  # contacts can have heterogeneous fields
    name: str
    title: Optional[str] = None
    seniority: Optional[str] = None
    persona: Optional[str] = None
    persona_fit_score: Optional[float] = None
    linkedin: Optional[str] = None
    email: Optional[str] = None


class ClayContact(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    title: Optional[str] = None
    linkedin: Optional[str] = None
    email: Optional[str] = None
    tagged_use_case: Optional[str] = None
    found_in_prod: bool = False


class AccountNode(BaseModel):
    """Per-account joined record built by repository.py."""

    model_config = ConfigDict(extra="forbid")

    # Identity
    account_id_18: str
    account_id_15: str
    account_name: str
    domain: Optional[str] = None

    # Ownership — authoritative source is Account-Data
    ownership: Ownership

    # Account profile
    segment: Optional[str] = None
    acv_usd: Optional[float] = None
    target_departments: list[str] = Field(default_factory=list)
    sales_model: Optional[str] = None
    target_customers: list[str] = Field(default_factory=list)

    # Current state — drives trigger + DQ
    use_case_gap_field: Optional[str] = None  # Expansion Data!K (the trigger)
    adoption_health: Optional[str] = None  # Expansion Data!S  (DQ1)
    last_activity_date: Optional[date] = None  # Account-Data!AG (DQ2)
    plan_end_date: Optional[date] = None  # Account-Data IU (rank)
    latest_expansion_contract_end: Optional[date] = None  # fallback for plan_end
    has_open_expansion_opp: bool = False  # Account-Data 196 (DQ4)
    is_active_customer: bool = True  # Account-Data 207 (DQ5)
    inactive_over_90_days: bool = False  # Account-Data 205 (DQ5)
    health_status: Optional[str] = None  # Account-Data 198

    # Usage rollups
    usage: UsageCounts = Field(default_factory=UsageCounts)

    # External signals
    signals_1p: Signals1P = Field(default_factory=Signals1P)
    signals_2p: Signals2P = Field(default_factory=Signals2P)
    signals_3p: Signals3P = Field(default_factory=Signals3P)
    icp_population: IcpPopulation = Field(default_factory=IcpPopulation)

    # Conversations
    conversations: Conversations = Field(default_factory=Conversations)

    # Contact pools
    contacts_in_product_sf: list[Contact] = Field(default_factory=list)
    contacts_not_in_product_clay: list[ClayContact] = Field(default_factory=list)

    # Data-quality flags discovered during the join
    data_quality_flags: list[str] = Field(default_factory=list)
