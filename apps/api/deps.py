"""Fake-login dependency + path helpers.

V1: no real auth. The frontend writes a cookie like ``session=role=AE&user=Bhargav%20Prasad``
on /login; this dependency parses it and exposes (role, user) to routes.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from fastapi import Cookie

# Resolve agent output dir relative to this file. apps/api/deps.py → apps/agent/output
HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = (HERE.parent / "agent" / "output").resolve()
DEFAULT_RUNLOG = (HERE.parent / "agent" / "run_log").resolve()


@dataclass
class CurrentUser:
    role: Optional[str]
    user: Optional[str]


def parse_session(cookie: Optional[str]) -> CurrentUser:
    if not cookie:
        return CurrentUser(role=None, user=None)
    parts = dict()
    for chunk in cookie.split("&"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = unquote(v.strip())
    return CurrentUser(role=parts.get("role"), user=parts.get("user"))


def current_user(session: Optional[str] = Cookie(default=None)) -> CurrentUser:
    return parse_session(session)


def slugify(name: str) -> str:
    s = name.strip().casefold()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


def output_dir() -> Path:
    return Path(os.environ.get("AGENT_OUTPUT_DIR", str(DEFAULT_OUTPUT)))


def run_log_dir() -> Path:
    return Path(os.environ.get("AGENT_RUN_LOG_DIR", str(DEFAULT_RUNLOG)))
