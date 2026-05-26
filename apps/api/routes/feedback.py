"""POST /api/feedback — writes a row to run_log/outcomes.csv."""

from __future__ import annotations

import csv
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deps import CurrentUser, current_user, run_log_dir

router = APIRouter()


class FeedbackIn(BaseModel):
    signal_id: str
    run_id: Optional[str] = None
    relevant: Optional[bool] = None
    actioned: Optional[bool] = None
    notes: str = ""


@router.post("/feedback")
def submit_feedback(payload: FeedbackIn, user: CurrentUser = Depends(current_user)) -> dict:
    path = run_log_dir() / "outcomes.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "run_id", "signal_id", "user", "role", "relevant", "actioned", "notes"])
        w.writerow([
            datetime.utcnow().isoformat(),
            payload.run_id or (payload.signal_id.split(":", 1)[0] if ":" in payload.signal_id else ""),
            payload.signal_id,
            user.user or "anon",
            user.role or "unknown",
            "" if payload.relevant is None else ("true" if payload.relevant else "false"),
            "" if payload.actioned is None else ("true" if payload.actioned else "false"),
            payload.notes,
        ])
    return {"ok": True}
