"""POST /api/agent/run and /api/agent/run/dry — fire a new run (RevOps/Admin)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from deps import CurrentUser, current_user

router = APIRouter()

AGENT_DIR = (Path(__file__).resolve().parent.parent.parent / "agent").resolve()


def _spawn(subcommand: list[str]) -> str:
    """Spawn `uv run python -m cli ...` in the agent dir; returns the started PID."""
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "cli", *subcommand],
        cwd=str(AGENT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return str(proc.pid)


def _require_admin_or_revops(user: CurrentUser):
    if user.role not in {"RevOps", "Admin"}:
        raise HTTPException(403, "only RevOps or Admin can trigger runs")


@router.post("/agent/run")
def trigger_full_run(
    bg: BackgroundTasks, user: CurrentUser = Depends(current_user)
) -> dict:
    _require_admin_or_revops(user)
    pid = _spawn(["run"])
    return {"queued": True, "pid": pid}


@router.post("/agent/run/dry")
def trigger_dry_run(
    bg: BackgroundTasks, user: CurrentUser = Depends(current_user)
) -> dict:
    _require_admin_or_revops(user)
    pid = _spawn(["dry-run"])
    return {"queued": True, "pid": pid}
