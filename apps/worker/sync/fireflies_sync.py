"""Fireflies → Supabase sync (meeting transcripts + AI summaries).

Fireflies exposes a GraphQL API — we use the `transcripts` query.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

from sync.account_resolver import AccountResolver, email_to_domain, INTERNAL_DOMAINS

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("fireflies_sync")

FF_ENDPOINT = "https://api.fireflies.ai/graphql"


def _gql(query: str, variables: dict | None = None) -> dict:
    r = httpx.post(
        FF_ENDPOINT,
        json={"query": query, "variables": variables or {}},
        headers={
            "Authorization": f"Bearer {os.environ['FIREFLIES_API_KEY']}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


TRANSCRIPTS_QUERY = """
query Transcripts($fromDate: DateTime, $toDate: DateTime, $limit: Int, $skip: Int) {
  transcripts(fromDate: $fromDate, toDate: $toDate, limit: $limit, skip: $skip) {
    id
    title
    date
    duration
    organizer_email
    participants
    summary {
      gist
      bullet_gist
      action_items
      keywords
      overview
    }
    meeting_attendees {
      displayName
      email
    }
  }
}
"""


def _fetch_transcripts(from_dt: datetime, to_dt: datetime) -> list[dict]:
    transcripts: list[dict] = []
    skip = 0
    limit = 50
    while True:
        data = _gql(TRANSCRIPTS_QUERY, {
            "fromDate": from_dt.isoformat() + "Z",
            "toDate": to_dt.isoformat() + "Z",
            "limit": limit,
            "skip": skip,
        })
        batch = (data.get("data") or {}).get("transcripts") or []
        transcripts.extend(batch)
        if len(batch) < limit:
            break
        skip += limit
    return transcripts


def _resolve_account(t: dict, resolver: AccountResolver) -> str | None:
    """Resolve account from meeting attendees — use domain + display name together."""
    # First pass: attendees with both name and email
    for attendee in t.get("meeting_attendees") or []:
        email = attendee.get("email", "")
        dom = email_to_domain(email)
        if dom and dom not in INTERNAL_DOMAINS:
            display_name = attendee.get("displayName") or attendee.get("name")
            return resolver.resolve(name=display_name, domain=dom, email=email)
    # Second pass: raw participants list (email strings only)
    for email in (t.get("participants") or []):
        dom = email_to_domain(email)
        if dom and dom not in INTERNAL_DOMAINS:
            return resolver.resolve(domain=dom, email=email)
    return None


def sync(sb: Client, resolver: AccountResolver, days_back: int = 90) -> None:
    to_dt = datetime.utcnow()
    from_dt = to_dt - timedelta(days=days_back)
    log.info("fireflies: fetching transcripts %s → %s", from_dt.date(), to_dt.date())

    transcripts = _fetch_transcripts(from_dt, to_dt)
    log.info("fireflies: %d transcripts to process", len(transcripts))

    rows = []
    for t in transcripts:
        acct_id = _resolve_account(t, resolver)
        summary = t.get("summary") or {}
        # action_items may be a string (bullet list) — split to list
        action_items_raw = summary.get("action_items") or ""
        if isinstance(action_items_raw, str):
            action_items = [l.strip("- •").strip() for l in action_items_raw.splitlines() if l.strip()]
        else:
            action_items = action_items_raw

        participant_emails = [
            a.get("email") for a in (t.get("meeting_attendees") or []) if a.get("email")
        ] or (t.get("participants") or [])

        # Fireflies returns date as Unix ms timestamp — convert to ISO
        raw_date = t.get("date")
        if isinstance(raw_date, (int, float)) and raw_date > 1e10:
            iso_date = datetime.utcfromtimestamp(raw_date / 1000).isoformat() + "Z"
        elif isinstance(raw_date, str):
            iso_date = raw_date
        else:
            iso_date = None

        rows.append({
            "id": t["id"],
            "account_id": acct_id,
            "title": t.get("title"),
            "date": iso_date,
            "duration_secs": int(t["duration"]) if t.get("duration") is not None else None,
            "organizer_email": t.get("organizer_email"),
            "participant_emails": participant_emails,
            "summary": summary.get("overview") or summary.get("gist"),
            "action_items": action_items,
            "key_questions": summary.get("keywords") or [],
            "outline": (summary.get("bullet_gist") or "").splitlines(),
            "raw": {"summary": summary, "title": t.get("title")},
            "synced_at": datetime.utcnow().isoformat(),
        })

    if rows:
        for i in range(0, len(rows), 200):
            sb.table("fireflies_meetings").upsert(rows[i:i+200], on_conflict="id").execute()
    log.info("fireflies: upserted %d transcripts", len(rows))


def run(days_back: int = 90) -> None:
    log.info("fireflies sync starting…")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)
    sync(sb, resolver, days_back=days_back)
    log.info("fireflies sync done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
