"""HARD GATE: funnel test against the real xlsx.

The spec pins the exact funnel: 117 → 104 → 77 → 54 → 48 → 46 → 44 (today=2026-05-18).
If this test ever fails, STOP — do not advance to ranking or reasoning.

Also locks the AE/CSM survivor splits and validates a notification fires for every drop.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from src.filter_logic import run_filter
from src.repository import Repository

XLSX = Path(__file__).resolve().parent.parent.parent.parent / "data" / "Expansion_Agent_1.xlsx"
TODAY = date(2026, 5, 18)


@pytest.fixture(scope="module")
def result():
    repo = Repository(XLSX)
    nodes = repo.load_accounts()
    return run_filter(nodes, TODAY)


def test_funnel_exact(result):
    funnel = result.funnel()
    assert funnel == {
        "total": 117,
        "triggered": 104,
        "after_DQ1": 77,
        "after_DQ2": 54,
        "after_DQ3": 48,
        "after_DQ4": 46,
        "after_DQ5": 44,
        "survivors": 44,
    }


def test_dq_counts_match_spec(result):
    assert result.dq_counts == {
        "DQ1_red_adoption": 27,
        "DQ2_recent_activity": 23,
        "DQ3_named_open_opp": 6,
        "DQ4_open_opp_flag": 2,
        "DQ5_inactive": 2,
    }


def test_survivor_ae_split(result):
    hist = Counter(n.ownership.ae_name for n in result.survivors)
    assert hist == Counter(
        {
            "Bhargav Prasad": 21,
            "Brooks Marsi": 16,
            "Mark Whalen": 6,
            "Paul Singh": 1,
        }
    )


def test_survivor_csm_split(result):
    hist = Counter(n.ownership.csm_name for n in result.survivors)
    assert hist == Counter(
        {
            "Janhvi Gupta": 23,
            "Aastha Jindal": 11,
            "Saumitra Shekhar": 6,
            "Joe Huisman": 4,
        }
    )


def test_every_disqualified_account_has_a_notification(result):
    dropped = sum(result.dq_counts.values())
    assert dropped == 60
    assert len(result.notifications) == dropped


def test_survivors_have_valid_ownership(result):
    """All 44 survivors must have both an AE and a CSM (per §4 data-quality reality)."""
    for n in result.survivors:
        assert n.ownership.ae_name is not None, f"{n.account_name} missing AE"
        assert n.ownership.csm_name is not None, f"{n.account_name} missing CSM"


def test_dual_routing_jointly_owned_count(result):
    """§12 mentions 13 accounts jointly owned by Bhargav+Janhvi. Confirms dual-routing
    is well-defined (same AccountNode appears in both queues)."""
    bhargav_janhvi = [
        n for n in result.survivors
        if n.ownership.ae_name == "Bhargav Prasad" and n.ownership.csm_name == "Janhvi Gupta"
    ]
    assert len(bhargav_janhvi) == 13
