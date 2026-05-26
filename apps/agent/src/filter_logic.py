"""Step 1 (trigger) + Step 2 (DQ1–DQ5) of the build spec.

Pure functions over AccountNode lists. The orchestrator (LangGraph) calls
these — they don't touch files or state.

Every disqualified account emits a Notification so the AE and CSM see *why*
it was dropped. The notification is the transparency contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Optional

from config.open_expansion_opps import is_open_opp_account
from schemas.account_node import AccountNode
from schemas.notification import DisqualifierRule, InvestigateDetail, Notification

# --- Step 1: trigger -------------------------------------------------------


def is_triggered(node: AccountNode) -> bool:
    """Step 1: account triggers if Expansion Data!K has any non-empty value."""
    return bool(node.use_case_gap_field and node.use_case_gap_field.strip())


def filter_triggered(nodes: Iterable[AccountNode]) -> tuple[list[AccountNode], list[AccountNode]]:
    """Split into (triggered, not_triggered)."""
    triggered: list[AccountNode] = []
    skipped: list[AccountNode] = []
    for n in nodes:
        (triggered if is_triggered(n) else skipped).append(n)
    return triggered, skipped


# --- Step 2: disqualifiers -------------------------------------------------


@dataclass
class DQHit:
    rule: DisqualifierRule
    explanation: str


def dq1_red_adoption(node: AccountNode) -> Optional[DQHit]:
    if node.adoption_health and node.adoption_health.strip().casefold() == "red":
        return DQHit(
            "DQ1_red_adoption",
            "Adoption Health from Prod is Red — adoption needs to recover before expansion.",
        )
    return None


def dq2_recent_activity(node: AccountNode, today: date, window_days: int = 30) -> Optional[DQHit]:
    if node.last_activity_date is None:
        return None
    delta = (today - node.last_activity_date).days
    # Spec: today - last_activity < 30 days  → drop (recently engaged)
    if 0 <= delta < window_days:
        return DQHit(
            "DQ2_recent_activity",
            f"Last Activity {delta}d ago (<{window_days}d) — recently engaged, skipping for one week.",
        )
    return None


def dq3_named_open_opp(node: AccountNode) -> Optional[DQHit]:
    if is_open_opp_account(node.account_name):
        return DQHit(
            "DQ3_named_open_opp",
            f"{node.account_name} is on the hardcoded open-expansion-opp list.",
        )
    return None


def dq4_open_opp_flag(node: AccountNode) -> Optional[DQHit]:
    if node.has_open_expansion_opp:
        return DQHit(
            "DQ4_open_opp_flag",
            "Account-Data flags an open expansion opportunity — AE already working it.",
        )
    return None


def dq5_inactive(node: AccountNode) -> Optional[DQHit]:
    if not node.is_active_customer:
        return DQHit(
            "DQ5_inactive",
            "Account-Data marks this as not an active customer.",
        )
    if node.inactive_over_90_days:
        return DQHit(
            "DQ5_inactive",
            "Account-Data marks this account inactive for >90 days.",
        )
    return None


# Order matters — first hit wins (so the funnel splits cleanly per the spec table).
DQ_ORDER = (
    ("DQ1", dq1_red_adoption),
    ("DQ2", dq2_recent_activity),
    ("DQ3", dq3_named_open_opp),
    ("DQ4", dq4_open_opp_flag),
    ("DQ5", dq5_inactive),
)


def evaluate_disqualifiers(node: AccountNode, today: date) -> Optional[DQHit]:
    """Apply DQ1–DQ5 in order. Return the first hit (or None if survivor)."""
    for key, fn in DQ_ORDER:
        # dq2 needs today; the rest don't.
        hit = fn(node, today) if key == "DQ2" else fn(node)
        if hit is not None:
            return hit
    return None


def _investigate_detail(node: AccountNode, hit: DQHit, today: date) -> InvestigateDetail:
    """Build the rich Investigate panel payload for a disqualified account."""
    last_activity_days = (
        (today - node.last_activity_date).days if node.last_activity_date else None
    )
    renewal_days = (
        (node.plan_end_date - today).days if node.plan_end_date else None
    )

    # Factor breakdown — every input that mattered, with positive/negative tag
    factors: list[dict] = [
        {
            "factor": "Use case gap detected",
            "value": node.use_case_gap_field or "—",
            "impact": "positive" if node.use_case_gap_field else "neutral",
        },
        {
            "factor": "Adoption health",
            "value": node.adoption_health or "Unknown",
            "impact": (
                "negative"
                if (node.adoption_health or "").casefold() == "red"
                else "positive"
                if (node.adoption_health or "").casefold() == "green"
                else "neutral"
            ),
        },
        {
            "factor": "Last activity",
            "value": (
                f"{last_activity_days} days ago"
                if last_activity_days is not None
                else "No activity logged"
            ),
            "impact": (
                "negative"
                if last_activity_days is not None and last_activity_days < 30
                else "positive"
                if last_activity_days is not None and last_activity_days <= 90
                else "neutral"
            ),
        },
        {
            "factor": "Renewal proximity",
            "value": (
                f"{renewal_days} days to renewal"
                if renewal_days is not None
                else "Renewal date unknown"
            ),
            "impact": (
                "positive"
                if renewal_days is not None and 0 <= renewal_days <= 180
                else "neutral"
            ),
        },
        {
            "factor": "Open expansion opp flag",
            "value": "Yes — AE is already working it" if node.has_open_expansion_opp else "No",
            "impact": "negative" if node.has_open_expansion_opp else "positive",
        },
        {
            "factor": "Customer status",
            "value": "Active" if node.is_active_customer else "Inactive",
            "impact": "positive" if node.is_active_customer else "negative",
        },
    ]

    # Risk indicators based on the rule hit + the node state
    risks: list[str] = []
    if hit.rule == "DQ1_red_adoption":
        risks.append("Product adoption is Red — fix adoption before introducing expansion ask.")
        risks.append("Customer is likely not deriving full value yet; new use case will struggle.")
    elif hit.rule == "DQ2_recent_activity":
        risks.append(
            f"Last activity was {last_activity_days} days ago — customer was recently touched, "
            "another outreach now risks looking pushy."
        )
        risks.append("Same use case was likely pitched in the last 30 days.")
    elif hit.rule == "DQ3_named_open_opp":
        risks.append("Account is on the named open-expansion-opp list — AE is already in motion.")
        risks.append("Dual outreach would cause internal confusion.")
    elif hit.rule == "DQ4_open_opp_flag":
        risks.append("Salesforce has an open expansion opportunity flagged on this account.")
        risks.append("Wait for the current opp to resolve before introducing a parallel pitch.")
    elif hit.rule == "DQ5_inactive":
        risks.append("Account is marked inactive or has been dormant for >90 days.")
        risks.append("Expansion isn't the play — adoption recovery or churn-risk is.")

    # What would qualify
    qualify_map = {
        "DQ1_red_adoption": "Adoption health moves from Red to Yellow or Green (typically after a successful re-engagement plan).",
        "DQ2_recent_activity": "30 days pass with no further pitch on the same use case.",
        "DQ3_named_open_opp": "The named open opportunity closes (won or lost), opening room for a new pitch.",
        "DQ4_open_opp_flag": "The open expansion opp in Salesforce is closed — then this account re-qualifies.",
        "DQ5_inactive": "Customer becomes active again (logs a session, runs an event, replies to outreach).",
    }

    why_disqualified_map = {
        "DQ1_red_adoption": (
            f"{node.account_name} shows a Red adoption health signal. The data tells us they're not "
            "getting full value from what they already bought — pitching an expansion use case now "
            "would land badly. The right play this week is adoption recovery, not expansion."
        ),
        "DQ2_recent_activity": (
            f"We touched {node.account_name} just {last_activity_days} days ago. Reaching out again "
            "on a new use case so soon would feel like a dogpile. The dataset prefers a 30-day "
            "cooling window between pitches."
        ),
        "DQ3_named_open_opp": (
            f"{node.account_name} is on the team's named open-expansion-opp list. The AE has "
            "already opened a conversation; surfacing a parallel signal would create internal "
            "confusion. Once that opp closes, this account re-enters consideration."
        ),
        "DQ4_open_opp_flag": (
            "Salesforce has an open expansion opportunity flagged on this account. The AE is "
            "already working it — a second signal would duplicate effort and risk confusing the "
            "customer."
        ),
        "DQ5_inactive": (
            "This account is marked inactive (or has been dormant for over 90 days). Expansion "
            "isn't the right motion here — the team needs to first reignite usage or determine "
            "whether to wind the customer down."
        ),
    }

    return InvestigateDetail(
        why_disqualified=why_disqualified_map.get(hit.rule, hit.explanation),
        what_would_qualify=qualify_map.get(hit.rule, "Conditions for re-qualification not defined."),
        factor_breakdown=factors,
        risk_indicators=risks,
        data_quality_notes=list(node.data_quality_flags),
        adoption_health=node.adoption_health,
        last_activity_days_ago=last_activity_days,
        renewal_proximity_days=renewal_days,
        has_open_expansion_opp=node.has_open_expansion_opp,
        is_active_customer=node.is_active_customer,
    )


def make_notification(node: AccountNode, hit: DQHit, today: date) -> Notification:
    return Notification(
        account_id=node.account_id_15,
        account_name=node.account_name,
        ae=node.ownership.ae_name,
        csm=node.ownership.csm_name,
        detected_gap=node.use_case_gap_field or "(unknown)",
        disqualifier_rule=hit.rule,
        explanation=hit.explanation,
        want_more_info=True,
        investigate=_investigate_detail(node, hit, today),
    )


# --- Aggregate API used by the orchestrator --------------------------------


@dataclass
class FilterResult:
    triggered: list[AccountNode] = field(default_factory=list)
    non_triggered: list[AccountNode] = field(default_factory=list)
    survivors: list[AccountNode] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    dq_counts: dict[str, int] = field(default_factory=dict)

    def funnel(self) -> dict[str, int]:
        """Returns the staged funnel counts for logging / tests."""
        # Counts shown after each DQ is applied, in order. Each stage = previous - dq_count.
        order: list[tuple[str, str]] = [
            ("DQ1", "DQ1_red_adoption"),
            ("DQ2", "DQ2_recent_activity"),
            ("DQ3", "DQ3_named_open_opp"),
            ("DQ4", "DQ4_open_opp_flag"),
            ("DQ5", "DQ5_inactive"),
        ]
        running = len(self.triggered)
        out: dict[str, int] = {
            "total": len(self.triggered) + len(self.non_triggered),
            "triggered": running,
        }
        for label, key in order:
            running -= self.dq_counts.get(key, 0)
            out[f"after_{label}"] = running
        out["survivors"] = len(self.survivors)
        return out


def run_filter(nodes: Iterable[AccountNode], today: date) -> FilterResult:
    """Apply Step 1 + Step 2 across the population."""
    triggered, non_triggered = filter_triggered(nodes)

    survivors: list[AccountNode] = []
    notifications: list[Notification] = []
    dq_counts: dict[str, int] = {}

    for node in triggered:
        hit = evaluate_disqualifiers(node, today)
        if hit is None:
            survivors.append(node)
        else:
            dq_counts[hit.rule] = dq_counts.get(hit.rule, 0) + 1
            notifications.append(make_notification(node, hit, today))

    return FilterResult(
        triggered=triggered,
        non_triggered=non_triggered,
        survivors=survivors,
        notifications=notifications,
        dq_counts=dq_counts,
    )
