"""Name → slug map for queue file routing.

Derived at runtime from the data; this module just exposes the slugifier
and a stable known-roster for reference. Names not in the roster still
work — they're slugified on the fly.
"""

from __future__ import annotations

import re


def slugify(name: str | None) -> str:
    """Filesystem-safe identifier. ``"Bhargav Prasad" -> "bhargav-prasad"``."""
    if not name:
        return "unknown"
    s = name.strip().casefold()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unknown"


# Reference only — actual list is derived from the run output.
KNOWN_AES: tuple[str, ...] = (
    "Bhargav Prasad",
    "Brooks Marsi",
    "Mark Whalen",
    "Paul Singh",
)

KNOWN_CSMS: tuple[str, ...] = (
    "Janhvi Gupta",
    "Aastha Jindal",
    "Saumitra Shekhar",
    "Joe Huisman",
)
