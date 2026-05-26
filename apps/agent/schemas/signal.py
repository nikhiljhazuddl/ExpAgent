"""Signal — the structured output the reasoning agent emits per account.

Schema is enforced via Pydantic validation on every Claude response. JSON-mode
guarantees JSON; this enforces shape. Mirrors §7 of the build spec.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

MissingUseCase = Literal["Webinar", "Field Events", "Third-Party Events", "Conferences"]
PriorityBand = Literal["high", "medium", "low"]
ActionOwner = Literal["AE", "CSM", "BOTH"]
BuyingRole = Literal["economic_buyer", "champion", "influencer", "user"]
ContactSource = Literal["sf", "clay"]


class SignalOwner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    role: Optional[str] = None


class SignalOwnership(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ae: SignalOwner = Field(default_factory=SignalOwner)
    csm: SignalOwner = Field(default_factory=SignalOwner)


class TargetPersona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    title: str
    buying_role: BuyingRole
    source: ContactSource
    linkedin: Optional[str] = None
    why_this_person: str


class WhoToTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    primary: TargetPersona
    secondary: Optional[TargetPersona] = None


class DraftOutreach(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    body: str


class ModelMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class ExplanationBullet(BaseModel):
    """One bullet point with a source citation.

    text:   the human-readable claim
    source: where the claim comes from — e.g., "Expansion Data col K", "Account-Data col AG",
            "Gong call summary", "Clay hiring count col AB", "Zuddl ontology — Sales-Led playbook"
    """

    model_config = ConfigDict(extra="forbid")
    text: str
    source: str


class OntologyGrounding(BaseModel):
    """Cites the Zuddl GTM ontology entities the agent used to reach this signal.

    Every kept signal must ground itself in named entity IDs. See
    config/zuddl_ontology.py.
    """

    model_config = ConfigDict(extra="forbid")
    expansion_entity_id: Optional[str] = None  # EXP-001..EXP-007
    primary_pain_ids: list[str] = Field(default_factory=list)  # PAIN-001..PAIN-008
    trigger_ids: list[str] = Field(default_factory=list)  # TRIG-001..TRIG-006
    persona_entity_id: Optional[str] = None  # P-001..P-008
    competitor_referenced: Optional[str] = None  # Cvent | Bizzabo | Splash | etc.
    maturity_stage: Optional[int] = Field(default=None, ge=1, le=5)
    churn_indicators_present: list[str] = Field(default_factory=list)  # CHURN-001..006
    causal_chain: Optional[str] = None  # "Adoption Flywheel" | "Enterprise Expansion" | etc.


class Signal(BaseModel):
    """Reasoning agent output.

    When ``is_signal=false`` only ``account_id``, ``account_name``, ``is_signal``,
    and ``reasoning_trace`` are required (everything else is optional).
    """

    model_config = ConfigDict(extra="forbid")

    # Required always
    account_id: str
    account_name: str
    is_signal: bool
    reasoning_trace: str

    # Required when is_signal=true
    missing_use_case: Optional[MissingUseCase] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    priority_band: Optional[PriorityBand] = None
    recommended_action_owner: Optional[ActionOwner] = None
    ownership: Optional[SignalOwnership] = None
    why_now: Optional[str] = None
    whats_missing: Optional[str] = None
    who_to_target: Optional[WhoToTarget] = None
    supporting_context: Optional[list["ExplanationBullet"]] = None  # bullets with source
    draft_outreach: Optional[DraftOutreach] = None

    # Business-brain enrichment (the "why" layer)
    business_logic: Optional[str] = None  # The reasoning chain from data → ontology → conclusion
    ontology_grounding: Optional[OntologyGrounding] = None

    # Natural-language explanations (the human-facing "why" layer) — BULLETS WITH SOURCE.
    # Every bullet cites where the data came from (e.g., "Expansion Data col U",
    # "Account-Data col IU", "Gong call summary"). Internal taxonomy IDs stay in
    # `ontology_grounding`, never in these bullets.
    explanation_why_prioritized: Optional[list["ExplanationBullet"]] = None
    explanation_pain_points: Optional[list["ExplanationBullet"]] = None
    explanation_maturity: Optional[list["ExplanationBullet"]] = None
    explanation_triggers: Optional[list["ExplanationBullet"]] = None
    explanation_expansion_thesis: Optional[list["ExplanationBullet"]] = None

    # Orchestrator-computed (not Claude). Settable post-hoc.
    priority_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    final_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    # Bookkeeping
    model_metadata: ModelMetadata = Field(default_factory=ModelMetadata)
    pii_present: bool = False
    data_quality_flag: Optional[str] = None

    @model_validator(mode="after")
    def _require_fields_when_signal(self) -> "Signal":
        if self.is_signal:
            missing = [
                name
                for name, value in (
                    ("missing_use_case", self.missing_use_case),
                    ("confidence", self.confidence),
                    ("priority_band", self.priority_band),
                    ("recommended_action_owner", self.recommended_action_owner),
                    ("why_now", self.why_now),
                    ("whats_missing", self.whats_missing),
                    ("who_to_target", self.who_to_target),
                    ("supporting_context", self.supporting_context),
                    ("draft_outreach", self.draft_outreach),
                )
                if value is None
            ]
            if missing:
                raise ValueError(
                    f"is_signal=true requires fields: {', '.join(missing)}"
                )
        return self


Signal.model_rebuild()
