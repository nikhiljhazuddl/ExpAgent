"""GET /api/signals and /api/signals/{id}.

Reads signals from Supabase `agent_runs` table (preferred) and falls back to
local JSON files. This makes Vercel/Render deployments work without needing
to ship JSON files in the bundle — the agent persists every run to Supabase
and the API reads the latest one.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from deps import output_dir, slugify

router = APIRouter()


def _supabase_client():
    """Return a cached Supabase client (None if env not set)."""
    global _SB
    try:
        return _SB
    except NameError:
        pass
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not (url and key):
        _SB = None  # type: ignore
        return None
    try:
        from supabase import create_client
        _SB = create_client(url, key)  # type: ignore
        return _SB
    except Exception:
        _SB = None  # type: ignore
        return None


def _latest_run_payload() -> dict:
    """Read the latest persisted run payload from Supabase agent_runs table."""
    sb = _supabase_client()
    if sb is None:
        return {}
    try:
        r = (sb.table("agent_runs")
             .select("run_id, generated_at, signals, queues_by_csm, queues_by_ae, run_summary")
             .order("generated_at", desc=True)
             .limit(1)
             .execute())
        if r.data:
            return r.data[0]
    except Exception:
        return {}
    return {}


def _load_all_signals() -> list[dict]:
    # Supabase first
    payload = _latest_run_payload()
    if payload and payload.get("signals"):
        sigs = payload["signals"]
        # signals may be stored as list or JSON object — normalize
        if isinstance(sigs, dict):
            sigs = sigs.get("signals", [])
        return sigs
    # Fallback to disk (for local dev)
    p = output_dir() / "signals.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("signals", [])


def _load_queue_full(role: str, user: str) -> dict:
    """Returns both `signals` (top N) and `extras` (next N) for the user's queue."""
    role_key = "queues_by_ae" if role.upper() == "AE" else "queues_by_csm"
    role_dir = "by_ae" if role.upper() == "AE" else "by_csm"

    # Supabase first
    payload = _latest_run_payload()
    queues = payload.get(role_key) if payload else None
    if queues:
        slug = slugify(user)
        # queues can be keyed by slug or by user_id
        for key, val in queues.items():
            if slugify(key) == slug:
                return {"signals": val.get("signals", []), "extras": val.get("extras", [])}
        return {"signals": [], "extras": []}

    # Fallback to disk
    p = output_dir() / "queues" / role_dir / f"{slugify(user)}.json"
    if not p.exists():
        return {"signals": [], "extras": []}
    payload2 = json.loads(p.read_text())
    return {"signals": payload2.get("signals", []), "extras": payload2.get("extras", [])}


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
