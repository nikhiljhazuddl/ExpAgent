"""Unit tests for reasoning.py using a mocked Claude client.

We don't hit the network in tests. Instead we monkeypatch _call_claude to return
canned responses (valid JSON, malformed, then valid on retry, etc.).
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from unittest.mock import patch

import pytest

from schemas.account_context import AccountContext, OwnerRef, OwnershipCtx
from schemas.signal import Signal
from src import reasoning

TODAY = date(2026, 5, 18)


def _make_context() -> AccountContext:
    return AccountContext(
        account_id="0015i00000ABC",
        account_name="TestCo",
        ownership=OwnershipCtx(
            ae=OwnerRef(name="Test AE", role="AE (Americas)"),
            csm=OwnerRef(name="Test CSM"),
        ),
        deterministic_priority_score=0.65,
    )


_VALID_PAYLOAD = {
    "account_id": "ignored_will_be_overwritten",
    "account_name": "ignored",
    "is_signal": True,
    "missing_use_case": "Field Events",
    "confidence": 0.82,
    "priority_band": "high",
    "recommended_action_owner": "BOTH",
    "ownership": {
        "ae": {"name": "Test AE", "role": "AE (Americas)"},
        "csm": {"name": "Test CSM"},
    },
    "why_now": "Renewal is 90 days away and hiring signals point to field motion.",
    "whats_missing": "Field events motion not yet operational.",
    "who_to_target": {
        "primary": {
            "name": "Sample Director",
            "title": "Director of Field Marketing",
            "buying_role": "champion",
            "source": "clay",
            "linkedin": None,
            "why_this_person": "Newly hired into the role.",
        },
        "secondary": None,
    },
    "supporting_context": [
        {"text": "Budget conversation in Gong call", "source": "Gong call summary"},
        {"text": "Field Marketing role posted", "source": "Expansion Data col AC"},
        {"text": "Renewal in 90 days", "source": "Account-Data col IU"},
    ],
    "draft_outreach": {"subject": "Field events at TestCo", "body": "Hi Sample, ..."},
    "reasoning_trace": "Confirmed gap; matched persona; high confidence.",
}


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    yield


@pytest.mark.asyncio
async def test_happy_path_validates(monkeypatch):
    async def fake_call(system, user, model, api_key):
        return json.dumps(_VALID_PAYLOAD), 100, 50

    monkeypatch.setattr(reasoning, "_call_claude", fake_call)

    sig = await reasoning.score_account(_make_context(), model="test-model")
    assert sig.is_signal is True
    assert sig.account_id == "0015i00000ABC"  # overwritten from context
    assert sig.priority_band == "high"
    assert sig.model_metadata.tokens_in == 100
    assert sig.model_metadata.model == "test-model"


@pytest.mark.asyncio
async def test_retry_on_validation_error_then_succeeds(monkeypatch):
    bad = {"account_id": "x", "account_name": "y", "is_signal": True, "reasoning_trace": "..."}
    good = _VALID_PAYLOAD
    calls: list[str] = []

    async def fake_call(system, user, model, api_key):
        calls.append("call")
        if len(calls) == 1:
            return json.dumps(bad), 100, 50
        return json.dumps(good), 100, 50

    monkeypatch.setattr(reasoning, "_call_claude", fake_call)

    sig = await reasoning.score_account(_make_context())
    assert sig.is_signal is True
    assert len(calls) == 2  # retried once


@pytest.mark.asyncio
async def test_final_failure_returns_validation_error_signal(monkeypatch):
    bad = {"account_id": "x", "account_name": "y", "is_signal": True, "reasoning_trace": "..."}

    async def fake_call(system, user, model, api_key):
        return json.dumps(bad), 100, 50

    monkeypatch.setattr(reasoning, "_call_claude", fake_call)

    sig = await reasoning.score_account(_make_context())
    assert sig.is_signal is False
    assert "validation_error" in (sig.reasoning_trace or "")


@pytest.mark.asyncio
async def test_extracts_json_from_fenced_response(monkeypatch):
    payload = "```json\n" + json.dumps(_VALID_PAYLOAD) + "\n```"

    async def fake_call(system, user, model, api_key):
        return payload, 10, 10

    monkeypatch.setattr(reasoning, "_call_claude", fake_call)

    sig = await reasoning.score_account(_make_context())
    assert sig.is_signal is True


@pytest.mark.asyncio
async def test_negative_signal_passes_through(monkeypatch):
    negative = {
        "account_id": "ignored",
        "account_name": "ignored",
        "is_signal": False,
        "reasoning_trace": "Gap contradicted by usage > 0 for the named use case.",
    }

    async def fake_call(system, user, model, api_key):
        return json.dumps(negative), 50, 20

    monkeypatch.setattr(reasoning, "_call_claude", fake_call)

    sig = await reasoning.score_account(_make_context())
    assert sig.is_signal is False
    assert "Gap contradicted" in sig.reasoning_trace


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # get_settings reads env each call; clear the cached settings module-level if needed
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        asyncio.run(reasoning.score_account(_make_context()))
