"""Pylon → Supabase sync (support issues / tickets).

Pylon API quirks:
  - Base URL: https://api.usepylon.com  (no /v1/ prefix)
  - /issues requires start_time + end_time, max 30-day window
  - /accounts has domain info for matching; owner is just {id} (no name)
  - assignee on issues is just {id} — we store the id and resolve names
    from the /accounts owner or fall back to SF CSM_owner__c in the agent.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

from sync.account_resolver import AccountResolver

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("pylon_sync")

PYLON_BASE = "https://api.usepylon.com"
WINDOW_DAYS = 28          # stay under 30-day limit
LOOKBACK_DAYS = 365       # how far back to pull issues (1 year)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['PYLON_API_KEY']}",
        "Content-Type": "application/json",
    }


def _get(path: str, params: dict | None = None) -> dict | list:
    url = f"{PYLON_BASE}{path}"
    r = httpx.get(url, headers=_headers(), params=params or {}, timeout=60)
    r.raise_for_status()
    return r.json()


def _fetch_accounts() -> dict[str, dict]:
    """Return {pylon_account_id: account_dict} for domain-based matching."""
    results: dict[str, dict] = {}
    page = 1
    while True:
        data = _get("/accounts", {"limit": 100, "page": page})
        items = data.get("data", []) if isinstance(data, dict) else []
        for a in items:
            results[a["id"]] = a
        if len(items) < 100:
            break
        page += 1
    log.info("pylon: fetched %d accounts for matching", len(results))
    return results


def _fetch_issues_window(start: datetime, end: datetime) -> list[dict]:
    """Fetch all issues in a time window (≤28 days)."""
    results: list[dict] = []
    page = 1
    while True:
        params = {
            "limit": 100,
            "page": page,
            "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        data = _get("/issues", params)
        items = data.get("data", []) if isinstance(data, dict) else []
        results.extend(items)
        if len(items) < 100:
            break
        page += 1
    return results


def _now() -> str:
    return datetime.utcnow().isoformat()


def sync(sb: Client, resolver: AccountResolver) -> None:
    # Fetch all Pylon accounts once for domain matching
    try:
        pylon_accounts = _fetch_accounts()
    except Exception as e:
        log.warning("pylon: could not fetch accounts (%s) — will match by email only", e)
        pylon_accounts = {}

    # Sliding 28-day windows from LOOKBACK_DAYS ago → now
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    window_start = now - timedelta(days=LOOKBACK_DAYS)

    all_issues: list[dict] = []
    current = window_start
    while current < now:
        end = min(current + timedelta(days=WINDOW_DAYS), now)
        try:
            batch = _fetch_issues_window(current, end)
            all_issues.extend(batch)
            log.info("pylon: window %s → %s fetched %d issues",
                     current.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), len(batch))
        except Exception as e:
            log.warning("pylon: window %s → %s failed: %s", current.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), e)
        current = end

    # Deduplicate by id (windows may overlap at edges)
    seen: set[str] = set()
    unique: list[dict] = []
    for issue in all_issues:
        iid = str(issue.get("id", ""))
        if iid and iid not in seen:
            seen.add(iid)
            unique.append(issue)

    log.info("pylon: %d unique issues to process", len(unique))

    rows = []
    for issue in unique:
        # Resolve account: use Pylon account.id → domain → resolver
        pylon_acct = issue.get("account") or {}
        pylon_acct_id = pylon_acct.get("id") if isinstance(pylon_acct, dict) else None
        pylon_acct_info = pylon_accounts.get(pylon_acct_id, {}) if pylon_acct_id else {}

        domain = pylon_acct_info.get("primary_domain") or pylon_acct_info.get("domain")
        name = pylon_acct_info.get("name")
        reporter_email = None
        if isinstance(issue.get("requester"), dict):
            reporter_email = issue["requester"].get("email")

        acct_id = None
        if name or domain or reporter_email:
            acct_id = resolver.resolve(name=name, domain=domain, email=reporter_email)

        # Assignee: Pylon returns {id: "..."} — store id, name stays None
        assignee = issue.get("assignee") or {}
        assignee_id = assignee.get("id") if isinstance(assignee, dict) else None

        rows.append({
            "id": str(issue["id"]),
            "account_id": acct_id,
            "title": issue.get("title") or issue.get("subject"),
            "status": issue.get("state") or issue.get("status"),
            "priority": (issue.get("custom_fields") or {}).get("priority", {}).get("value"),
            "category": issue.get("type"),
            "assignee_name": None,   # Pylon API doesn't expose name in issues list
            "reporter_email": reporter_email,
            "created_at": issue.get("created_at") or issue.get("createdAt"),
            "resolved_at": issue.get("resolved_at") or issue.get("resolvedAt"),
            "raw": issue,
            "synced_at": _now(),
        })

    if rows:
        for i in range(0, len(rows), 250):
            sb.table("pylon_issues").upsert(rows[i:i+250], on_conflict="id").execute()
    log.info("pylon: upserted %d issues", len(rows))


def run() -> None:
    log.info("pylon sync starting…")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)
    sync(sb, resolver)
    log.info("pylon sync done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
