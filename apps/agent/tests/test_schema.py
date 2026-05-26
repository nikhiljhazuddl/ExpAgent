"""Round-trip tests for the four schemas.

Asserts: every model serialises to JSON, deserialises back, and is exactly equal.
Also asserts the conditional-required-fields rule on Signal works.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from schemas import (
    AccountContext,
    AccountNode,
    ClayContact,
    Contact,
    Notification,
    Ownership,
    Signal,
)
from schemas.account_context import (
    AccountProfile,
    CurrentState,
    OwnerRef,
    OwnershipCtx,
    UsageCtx,
)
from schemas.signal import (
    DraftOutreach,
    SignalOwner,
    SignalOwnership,
    TargetPersona,
    WhoToTarget,
)


def _round_trip(obj):
    payload = obj.model_dump_json()
    rebuilt = obj.__class__.model_validate_json(payload)
    assert rebuilt == obj
    # also verify dict round-trip
    assert obj.__class__.model_validate(json.loads(payload)) == obj


def test_account_node_round_trip():
    node = AccountNode(
        account_id_18="0015i00000OrA0zAAA",
        account_id_15="0015i00000OrA0z",
        account_name="Zenoti",
        domain="zenoti.com",
        ownership=Ownership(
            ae_name="Bhargav Prasad", ae_role="AE (APAC)", csm_name="Janhvi Gupta"
        ),
        segment="Enterprise",
        acv_usd=32000.0,
        use_case_gap_field="Webinar; Third-Party Events",
        adoption_health="Yellow",
        last_activity_date=date(2026, 3, 1),
        plan_end_date=date(2026, 8, 15),
        contacts_in_product_sf=[
            Contact(name="Sarah Chen", title="VP Marketing", seniority="VP", persona="Marketing Leader", persona_fit_score=92.0),
        ],
        contacts_not_in_product_clay=[
            ClayContact(name="Priya Rao", title="Director Field Marketing", tagged_use_case="Field Events"),
        ],
    )
    _round_trip(node)


def test_account_context_round_trip():
    ctx = AccountContext(
        account_id="0015i00000OrA0z",
        account_name="Zenoti",
        ownership=OwnershipCtx(
            ae=OwnerRef(name="Bhargav Prasad", role="AE (APAC)"),
            csm=OwnerRef(name="Janhvi Gupta"),
        ),
        segment="Enterprise",
        acv_usd=32000.0,
        current_state=CurrentState(
            adoption_health="Yellow",
            active_use_cases_in_prod=["Flagship", "Webinars"],
            use_case_gap_field="Webinar; Third-Party Events",
            renewal_proximity_days=89,
            last_activity_days_ago=47,
        ),
        usage=UsageCtx(field_events_all_time=0, total_events_all_time=5, standard_in_person=4, standard_virtual=1),
        account_profile=AccountProfile(target_departments=["Marketing"], sales_model="Sales-led"),
        deterministic_priority_score=0.71,
    )
    _round_trip(ctx)


def test_signal_round_trip_positive():
    sig = Signal(
        account_id="0015i00000OrA0z",
        account_name="Zenoti",
        is_signal=True,
        missing_use_case="Field Events",
        confidence=0.84,
        priority_band="high",
        recommended_action_owner="BOTH",
        ownership=SignalOwnership(
            ae=SignalOwner(name="Bhargav Prasad", role="AE (APAC)"),
            csm=SignalOwner(name="Janhvi Gupta"),
        ),
        why_now="Renewal in 89 days; hiring an Event Marketing Manager last month.",
        whats_missing="Zenoti runs in-person ops but no field-events motion.",
        who_to_target=WhoToTarget(
            primary=TargetPersona(
                name="Priya Rao",
                title="Director of Field Marketing",
                buying_role="champion",
                source="clay",
                why_this_person="Newly hired role, exact match for the gap.",
            )
        ),
        supporting_context=[
            {"text": "Gong call mentions 'spa partner events'", "source": "Gong call summary"},
            {"text": "Field Marketing Manager hire posted 12 days ago", "source": "Expansion Data col AC (Field Events Hiring)"},
        ],
        draft_outreach=DraftOutreach(subject="Field events motion for Zenoti", body="Hi Priya, ..."),
        reasoning_trace="Gap confirmed → persona matched → high confidence.",
        priority_score=0.71,
        final_score=0.775,
    )
    _round_trip(sig)


def test_signal_negative_minimal():
    sig = Signal(
        account_id="0015i00000ZZZ",
        account_name="ExampleCo",
        is_signal=False,
        reasoning_trace="Gap not confirmed: usage shows webinar volume.",
    )
    _round_trip(sig)


def test_signal_positive_missing_required_fields_raises():
    with pytest.raises(ValidationError):
        Signal(
            account_id="x",
            account_name="y",
            is_signal=True,
            reasoning_trace="...",
            # missing why_now, whats_missing, etc.
        )


def test_signal_confidence_bounded():
    with pytest.raises(ValidationError):
        Signal(
            account_id="x",
            account_name="y",
            is_signal=False,
            reasoning_trace="...",
            confidence=1.5,
        )


def test_notification_round_trip():
    n = Notification(
        account_id="0015i00000OrA0z",
        account_name="Zenoti",
        ae="Bhargav Prasad",
        csm="Janhvi Gupta",
        detected_gap="Field Events",
        disqualifier_rule="DQ2_recent_activity",
        explanation="Last activity 12 days ago — recently engaged, skipping for one week.",
    )
    _round_trip(n)


def test_notification_unknown_rule_rejected():
    with pytest.raises(ValidationError):
        Notification(
            account_id="x",
            account_name="y",
            detected_gap="Webinar",
            disqualifier_rule="DQ99_made_up",  # type: ignore[arg-type]
            explanation="...",
        )
