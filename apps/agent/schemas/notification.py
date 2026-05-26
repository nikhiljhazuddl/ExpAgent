"""Notification — the transparency-log entry written every time an account is
detected as having a gap but is dropped by a disqualifier.

Routes to BOTH the AE and the CSM. Mirrors §7 of the build spec.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

DisqualifierRule = Literal[
    "DQ1_red_adoption",
    "DQ2_recent_activity",
    "DQ3_named_open_opp",
    "DQ4_open_opp_flag",
    "DQ5_inactive",
]


class Notification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str
    account_name: str
    ae: Optional[str] = None
    csm: Optional[str] = None
    detected_gap: str
    disqualifier_rule: DisqualifierRule
    explanation: str
    want_more_info: bool = True

    # Investigate-panel payload (populated by persist_node from the AccountNode)
    investigate: Optional["InvestigateDetail"] = None


class InvestigateDetail(BaseModel):
    """Rich explanation panel shown when an AE/CSM clicks 'Investigate' on a notification."""

    model_config = ConfigDict(extra="forbid")

    # Why disqualified — natural language summary
    why_disqualified: str
    what_would_qualify: str  # what would need to change for this account to re-qualify

    # Factor breakdown (every input that mattered)
    factor_breakdown: list[dict] = []  # [{factor, value, impact: positive|negative|neutral}]

    # Signals that reduced ranking
    risk_indicators: list[str] = []  # human-readable bullets
    data_quality_notes: list[str] = []

    # Adoption health snapshot
    adoption_health: Optional[str] = None
    last_activity_days_ago: Optional[int] = None
    renewal_proximity_days: Optional[int] = None
    has_open_expansion_opp: bool = False
    is_active_customer: bool = True


Notification.model_rebuild()
