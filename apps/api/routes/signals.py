"""GET /api/signals and /api/signals/{id}."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from deps import output_dir, slugify

router = APIRouter()


def _load_all_signals() -> list[dict]:
    p = output_dir() / "signals.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("signals", [])


def _load_queue(role: str, user: str) -> list[dict]:
    role_dir = "by_ae" if role.upper() == "AE" else "by_csm"
    p = output_dir() / "queues" / role_dir / f"{slugify(user)}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("signals", [])


def _load_queue_full(role: str, user: str) -> dict:
    """Returns both `signals` (top 5) and `extras` (ranks 6-10)."""
    role_dir = "by_ae" if role.upper() == "AE" else "by_csm"
    p = output_dir() / "queues" / role_dir / f"{slugify(user)}.json"
    if not p.exists():
        return {"signals": [], "extras": []}
    payload = json.loads(p.read_text())
    return {"signals": payload.get("signals", []), "extras": payload.get("extras", [])}


@router.get("/signals")
def list_signals(role: Optional[str] = Query(None), user: Optional[str] = Query(None)) -> dict:
    if not role:
        # RevOps / Admin default — return all kept signals
        return {"signals": _load_all_signals(), "extras": []}
    role_upper = role.upper()
    if role_upper in {"REVOPS", "ADMIN"}:
        return {"signals": _load_all_signals(), "extras": []}
    if not user:
        raise HTTPException(400, "role=AE|CSM requires user param")
    if role_upper not in {"AE", "CSM"}:
        raise HTTPException(400, "role must be AE | CSM | RevOps | Admin")
    return _load_queue_full(role_upper, user)


@router.get("/signals/{signal_id}")
def get_signal(signal_id: str) -> dict:
    for s in _load_all_signals():
        if s.get("id") == signal_id:
            return s
    raise HTTPException(404, f"signal {signal_id} not found")
