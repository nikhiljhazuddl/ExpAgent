"""GET /api/notifications."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from deps import output_dir, slugify

router = APIRouter()


@router.get("/notifications")
def list_notifications(role: Optional[str] = Query(None), user: Optional[str] = Query(None)) -> dict:
    if not role:
        return {"notifications": _load_all()}
    role_upper = role.upper()
    if role_upper in {"REVOPS", "ADMIN"}:
        return {"notifications": _load_all()}
    if role_upper not in {"AE", "CSM"}:
        raise HTTPException(400, "role must be AE | CSM | RevOps | Admin")
    if not user:
        raise HTTPException(400, "role=AE|CSM requires user param")
    return {"notifications": _load_for_user(role_upper, user)}


def _load_all() -> list[dict]:
    out = []
    base = output_dir() / "notifications"
    for sub in ("by_ae", "by_csm"):
        d = base / sub
        if not d.exists():
            continue
        for p in d.glob("*.json"):
            try:
                payload = json.loads(p.read_text())
                out.extend(payload.get("notifications", []))
            except (json.JSONDecodeError, OSError):
                continue
    # de-dup by (account_id, disqualifier_rule)
    seen = set()
    deduped = []
    for n in out:
        key = (n.get("account_id"), n.get("disqualifier_rule"))
        if key not in seen:
            seen.add(key)
            deduped.append(n)
    return deduped


def _load_for_user(role: str, user: str) -> list[dict]:
    sub = "by_ae" if role == "AE" else "by_csm"
    p = output_dir() / "notifications" / sub / f"{slugify(user)}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("notifications", [])
