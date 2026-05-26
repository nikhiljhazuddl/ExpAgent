"""FastAPI entry — serves the Expansion Agent output to the web app."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Ensure routes/ and deps.py are importable when run via `uv run uvicorn main:app`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from routes import accounts, agent, feedback, notifications, runs, signals, users  # noqa: E402

app = FastAPI(title="GTM Mesh — Expansion Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api"
app.include_router(users.router, prefix=PREFIX)
app.include_router(signals.router, prefix=PREFIX)
app.include_router(notifications.router, prefix=PREFIX)
app.include_router(runs.router, prefix=PREFIX)
app.include_router(feedback.router, prefix=PREFIX)
app.include_router(accounts.router, prefix=PREFIX)
app.include_router(agent.router, prefix=PREFIX)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}
