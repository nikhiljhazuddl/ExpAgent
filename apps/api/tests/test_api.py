"""Smoke tests for the FastAPI endpoints.

Requires the agent dry-run to have run at least once (so output/*.json exists).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from main import app  # noqa: E402

client = TestClient(app)


def test_healthz():
    assert client.get("/healthz").json() == {"ok": True}


def test_users_lists_discovered_aes_and_csms():
    r = client.get("/api/users")
    assert r.status_code == 200
    payload = r.json()
    assert payload["roles"] == ["AE", "CSM", "RevOps", "Admin"]
    aes = {u["name"] for u in payload["users"] if u["role"] == "AE"}
    csms = {u["name"] for u in payload["users"] if u["role"] == "CSM"}
    # The 4 named AEs/CSMs in the spec should be present
    for ae in ("Bhargav Prasad", "Brooks Marsi", "Mark Whalen", "Paul Singh"):
        assert ae in aes
    for csm in ("Janhvi Gupta", "Aastha Jindal", "Saumitra Shekhar", "Joe Huisman"):
        assert csm in csms


def test_me_reads_cookie():
    r = client.get("/api/me", cookies={"session": "role=CSM&user=Janhvi%20Gupta"})
    assert r.json() == {"role": "CSM", "user": "Janhvi Gupta"}


def test_runs_latest_returns_funnel():
    r = client.get("/api/runs/latest")
    assert r.status_code == 200
    funnel = r.json()["funnel"]
    assert funnel["triggered"] == 104
    assert funnel["survivors"] == 44


def test_signals_requires_user_when_ae_or_csm():
    assert client.get("/api/signals?role=AE").status_code == 400


def test_notifications_for_csm_returns_list():
    r = client.get("/api/notifications?role=CSM&user=Janhvi Gupta")
    assert r.status_code == 200
    assert isinstance(r.json()["notifications"], list)
