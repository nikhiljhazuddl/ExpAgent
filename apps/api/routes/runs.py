"""GET /api/runs and /api/runs/latest.

Reads from Supabase agent_runs (preferred) with fallback to local disk.
"""

from __future__ import annotations

import json
import os

from fastapi import APIRouter, HTTPException

from deps import output_dir

router = APIRouter()


def _sb():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not (url and key):
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception:
        return None


@router.get("/runs")
def list_runs() -> dict:
    sb = _sb()
    if sb is not None:
        try:
            r = (sb.table("agent_runs")
                 .select("run_id, generated_at, run_summary")
                 .order("generated_at", desc=True)
                 .limit(50)
                 .execute())
            runs = [{
                "run_id":       row["run_id"],
                "triggered_at": row["generated_at"],
                "funnel":       (row.get("run_summary") or {}).get("funnel", {}),
            } for row in (r.data or [])]
            if runs:
                return {"runs": runs}
        except Exception:
            pass
    p = output_dir() / "runs.json"
    if not p.exists():
        return {"runs": []}
    return {"runs": json.loads(p.read_text()).get("runs", [])}


@router.get("/runs/latest")
def latest_run() -> dict:
    sb = _sb()
    if sb is not None:
        try:
            r = (sb.table("agent_runs")
                 .select("run_id, generated_at, run_summary")
                 .order("generated_at", desc=True)
                 .limit(1)
                 .execute())
            if r.data:
                row = r.data[0]
                return {
                    "run_id":       row["run_id"],
                    "triggered_at": row["generated_at"],
                    **(row.get("run_summary") or {}),
                }
        except Exception:
            pass
    p = output_dir() / "run_summary.json"
    if not p.exists():
        raise HTTPException(404, "no runs yet")
    return json.loads(p.read_text())
