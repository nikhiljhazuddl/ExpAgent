"""Unit tests for the deterministic ranker.

Locks the math: adoption thresholds, renewal buckets, log1p normalization,
weighted sum, and sort order.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from schemas.account_node import AccountNode, Ownership, UsageCounts
from src.rank_logic import (
    adoption_score,
    rank_survivors,
    renewal_proximity_score,
    usage_strength,
)

TODAY = date(2026, 5, 18)


def _node(
    name: str,
    adoption: str | None = None,
    plan_end: date | None = None,
    usage_total: float = 0.0,
) -> AccountNode:
    return AccountNode(
        account_id_18=name.ljust(18, "x"),
        account_id_15=name.ljust(15, "x")[:15],
        account_name=name,
        ownership=Ownership(ae_name="Test AE", csm_name="Test CSM"),
        adoption_health=adoption,
        plan_end_date=plan_end,
        usage=UsageCounts(field_events_all_time=usage_total),
    )


def test_adoption_score_table():
    assert adoption_score("Green") == 1.0
    assert adoption_score("green") == 1.0
    assert adoption_score("Yellow") == 0.6
    assert adoption_score("Red") == 0.2
    assert adoption_score(None) == 0.4
    assert adoption_score("Mystery") == 0.4


def test_renewal_proximity_buckets():
    assert renewal_proximity_score(TODAY + timedelta(days=30), None, TODAY) == 1.0
    assert renewal_proximity_score(TODAY + timedelta(days=120), None, TODAY) == 1.0
    assert renewal_proximity_score(TODAY + timedelta(days=121), None, TODAY) == 0.6
    assert renewal_proximity_score(TODAY + timedelta(days=180), None, TODAY) == 0.6
    assert renewal_proximity_score(TODAY + timedelta(days=181), None, TODAY) == 0.3
    assert renewal_proximity_score(TODAY + timedelta(days=365), None, TODAY) == 0.3
    assert renewal_proximity_score(TODAY + timedelta(days=400), None, TODAY) == 0.1
    assert renewal_proximity_score(None, None, TODAY) == 0.4


def test_renewal_falls_back_to_latest_expansion():
    fb = TODAY + timedelta(days=60)
    assert renewal_proximity_score(None, fb, TODAY) == 1.0


def test_renewal_past_due_treated_as_imminent():
    assert renewal_proximity_score(TODAY - timedelta(days=10), None, TODAY) == 1.0


def test_usage_strength_normalization():
    out = usage_strength([0.0, 1.0, 10.0, 100.0], max_total=100.0)
    assert out[0] == 0.0
    assert math.isclose(out[3], 1.0, abs_tol=1e-9)
    # monotonically non-decreasing
    assert all(out[i] <= out[i + 1] for i in range(len(out) - 1))


def test_usage_strength_zero_max_safe():
    out = usage_strength([0.0, 0.0], max_total=0.0)
    assert out == [0.0, 0.0]


def test_rank_survivors_orders_by_priority():
    nodes = [
        _node("A", "Red", TODAY + timedelta(days=10), 0.0),       # low
        _node("B", "Green", TODAY + timedelta(days=30), 100.0),  # high
        _node("C", "Yellow", TODAY + timedelta(days=200), 10.0),  # medium
    ]
    ranked = rank_survivors(nodes, TODAY)
    names = [r.node.account_name for r in ranked]
    assert names[0] == "B"
    assert names[-1] == "A"
    # all bounded
    assert all(0.0 <= r.priority_score <= 1.0 for r in ranked)


def test_rank_empty_input_safe():
    assert rank_survivors([], TODAY) == []


def test_rank_priority_math_handworked():
    """Single-node case: priority = 0.4*1.0 + 0.3*1.0 + 0.3*0 = 0.70 (no other accounts → strength=0)."""
    n = _node("Solo", "Green", TODAY + timedelta(days=10), 0.0)
    ranked = rank_survivors([n], TODAY)
    assert ranked[0].adoption_score == 1.0
    assert ranked[0].renewal_proximity_score == 1.0
    assert ranked[0].usage_strength == 0.0
    assert pytest.approx(ranked[0].priority_score, abs=1e-9) == 0.70
