"""Gong → Supabase sync (Calls + AI insights)."""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

from sync.account_resolver import AccountResolver, email_to_domain, INTERNAL_DOMAINS

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("gong_sync")


def _auth_header() -> str:
    key = os.environ["GONG_ACCESS_KEY"]
    secret = os.environ["GONG_SECRET_KEY"]
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    return f"Basic {token}"


def _base() -> str:
    return os.environ.get("GONG_BASE_URL", "https://us-51250.api.gong.io")


def _get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(
        f"{_base()}{path}",
        headers={"Authorization": _auth_header()},
        params=params or {},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = httpx.post(
        f"{_base()}{path}",
        headers={"Authorization": _auth_header(), "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _fetch_calls(from_dt: str, to_dt: str) -> list[dict]:
    calls: list[dict] = []
    cursor: str | None = None
    while True:
        body: dict = {
            "filter": {"fromDateTime": from_dt, "toDateTime": to_dt},
            "contentSelector": {"context": "Extended", "contextTiming": ["Now"]},
        }
        if cursor:
            body["cursor"] = cursor
        data = _post("/v2/calls/extensive", body)
        calls.extend(data.get("calls", []))
        cursor = data.get("records", {}).get("cursor")
        if not cursor:
            break
    return calls


def _resolve_account_for_call(call: dict, resolver: AccountResolver) -> str | None:
    """Map a Gong call to a canonical account.

    Priority:
      1. CRM context block — has both account Name and Website/domain
      2. External attendee email domain (non-Zuddl, non-generic)
    """
    # 1 — CRM context (most reliable: name + domain together)
    for ctx in call.get("context", []):
        for obj in ctx.get("objects", []):
            if obj.get("objectType") == "Account":
                fields = {f.get("name"): f.get("value") for f in obj.get("fields", [])}
                name   = fields.get("Name")
                domain = fields.get("Website") or fields.get("Domain")
                if name or domain:
                    return resolver.resolve(name=name, domain=domain)

    # 2 — external attendee email domain
    for party in call.get("parties", []):
        email = party.get("emailAddress", "")
        dom = email_to_domain(email)
        if dom and dom not in INTERNAL_DOMAINS:
            # Also try company name from party metadata
            company_name = party.get("company") or party.get("accountName")
            return resolver.resolve(name=company_name, domain=dom, email=email)

    return None


def sync(sb: Client, resolver: AccountResolver, days_back: int = 90) -> None:
    to_dt = datetime.utcnow()
    from_dt = to_dt - timedelta(days=days_back)
    log.info("gong: fetching calls %s → %s", from_dt.date(), to_dt.date())

    calls = _fetch_calls(from_dt.isoformat() + "Z", to_dt.isoformat() + "Z")
    log.info("gong: %d calls to process", len(calls))

    rows = []
    for call in calls:
        acct_id = _resolve_account_for_call(call, resolver)
        speakers = [
            p.get("name") for p in call.get("parties", [])
            if p.get("speakerId") and p.get("name")
        ]
        emails = [p.get("emailAddress") for p in call.get("parties", []) if p.get("emailAddress")]

        content = call.get("content", {})
        rows.append({
            "id": call["metaData"]["id"],
            "account_id": acct_id,
            "title": call["metaData"].get("title"),
            "call_url": call["metaData"].get("url"),
            "direction": call["metaData"].get("direction"),
            "duration_secs": call["metaData"].get("duration"),
            "started_at": call["metaData"].get("started"),
            "speaker_names": speakers,
            "attendee_emails": emails,
            "topics": content.get("topics", []),
            "highlights": content.get("highlights", []),
            "action_items": content.get("pointsOfInterest", []),
            "key_points": content.get("keyPoints", []),
            "trackers_hit": [t["name"] for t in content.get("trackers", []) if t.get("name")],
            "raw": call.get("metaData", {}),
            "synced_at": datetime.utcnow().isoformat(),
        })

    if rows:
        # upsert in batches of 200
        for i in range(0, len(rows), 200):
            sb.table("gong_calls").upsert(rows[i:i+200], on_conflict="id").execute()
    log.info("gong: upserted %d calls", len(rows))


def run(days_back: int = 90) -> None:
    log.info("gong sync starting…")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)
    sync(sb, resolver, days_back=days_back)
    log.info("gong sync done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
