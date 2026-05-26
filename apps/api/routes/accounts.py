"""GET /api/accounts/{id} — read-only account context (from frozen contexts dir)."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from deps import run_log_dir

router = APIRouter()


@router.get("/accounts/{account_id}")
def get_account(account_id: str) -> dict:
    p = run_log_dir() / "contexts" / f"{account_id}.json"
    if not p.exists():
        raise HTTPException(404, f"no context for account {account_id}")
    return json.loads(p.read_text())
