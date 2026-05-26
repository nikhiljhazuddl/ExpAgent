"""GET /api/runs and /api/runs/latest."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from deps import output_dir

router = APIRouter()


@router.get("/runs")
def list_runs() -> dict:
    p = output_dir() / "runs.json"
    if not p.exists():
        return {"runs": []}
    return {"runs": json.loads(p.read_text()).get("runs", [])}


@router.get("/runs/latest")
def latest_run() -> dict:
    p = output_dir() / "run_summary.json"
    if not p.exists():
        raise HTTPException(404, "no runs yet")
    return json.loads(p.read_text())
