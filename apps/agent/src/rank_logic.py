"""Step 3 — deterministic ranking. Pure Python, no LLM.

priority_score = 0.40 * adoption_score
               + 0.30 * renewal_proximity_score
               + 0.30 * usage_strength

usage_strength = log1p(total_events_all_time) / log1p(max_total_across_survivors)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional

from schemas.account_node import AccountNode


def adoption_score(health: Optional[str]) -> float:
    """Green=1.0 · Yellow=0.6 · Red=0.2 · missing=0.4 (treat as Yellow-ish)."""
    if not health:
        return 0.4
    h = health.strip().casefold()
    if h == "green":
        return 1.0
    if h == "yellow":
        return 0.6
    if h == "red":
        return 0.2
    return 0.4


def renewal_proximity_score(
    plan_end: Optional[date], fallback: Optional[date], today: date
) -> float:
    """≤120d=1.0 · 121–180d=0.6 · 181–365d=0.3 · >365d=0.1 · missing=0.4."""
    target = plan_end or fallback
    if target is None:
        return 0.4
    days = (target - today).days
    if days < 0:
        # Past due — treat as imminent (renewal already needed).
        return 1.0
    if days <= 120:
        return 1.0
    if days <= 180:
        return 0.6
    if days <= 365:
        return 0.3
    return 0.1


def usage_strength(totals: Iterable[float], max_total: float) -> list[float]:
    """Continuous 0–1 via log1p normalization across the survivor cohort."""
    denom = math.log1p(max_total) if max_total > 0 else 1.0
    return [math.log1p(t) / denom if denom > 0 else 0.0 for t in totals]


@dataclass
class RankedCandidate:
    node: AccountNode
    adoption_score: float
    renewal_proximity_score: float
    usage_strength: float
    priority_score: float


def rank_survivors(survivors: list[AccountNode], today: date) -> list[RankedCandidate]:
    """Compute the priority_score for each survivor; returns sorted desc."""
    if not survivors:
        return []

    totals = [n.usage.total for n in survivors]
    max_total = max(totals) if totals else 0.0
    strengths = usage_strength(totals, max_total)

    out: list[RankedCandidate] = []
    for node, strength in zip(survivors, strengths):
        a = adoption_score(node.adoption_health)
        r = renewal_proximity_score(node.plan_end_date, node.latest_expansion_contract_end, today)
        priority = 0.40 * a + 0.30 * r + 0.30 * strength
        # Bound to [0,1] in case of any drift.
        priority = max(0.0, min(1.0, priority))
        out.append(
            RankedCandidate(
                node=node,
                adoption_score=a,
                renewal_proximity_score=r,
                usage_strength=strength,
                priority_score=priority,
            )
        )

    out.sort(key=lambda c: c.priority_score, reverse=True)
    return out
