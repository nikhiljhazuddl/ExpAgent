"""Pylon → Supabase sync (support issues / tickets)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

from sync.account_resolver import AccountResolver

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("pylon_sync")

PYLON_BASE = "https://api.usepylon.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['PYLON_API_KEY']}",
        "Content-Type": "application/json",
    }


def _paginate(path: str, params: dict | None = None) -> list[dict]:
    results: list[dict] = []
    url = f"{PYLON_BASE}{path}"
    p = dict(params or {})
    p.setdefault("limit", 100)
    page = 1
    while True:
        p["page"] = page
        r = httpx.get(url, headers=_headers(), params=p, timeout=60)
        if r.status_code == 404:
            break
        r.raise_for_status()
        data = r.json()
        # Pylon may return {"data": [...]} or {"issues": [...]} or a plain list
        if isinstance(data, list):
            batch = data
        else:
            batch = data.get("data") or data.get("issues") or data.get("results") or []
        results.extend(batch)
        if len(batch) < p["limit"]:
            break
        page += 1
    return results


def _now() -> str:
    return datetime.utcnow().isoformat()


def sync(sb: Client, resolver: AccountResolver) -> None:
    issues = _paginate("/v1/issues")
    log.info("pylon: %d issues to process", len(issues))

    rows = []
    for issue in issues:
        # Pylon has company name + domain — both passed together for best match
        company  = issue.get("company") or {}
        name     = company.get("name") or issue.get("account_name") or issue.get("customer_name")
        domain   = company.get("domain") or company.get("website")
        reporter = (issue.get("reporter") or {}).get("email") or (issue.get("customer") or {}).get("email")

        acct_id = None
        if name or domain or reporter:
            acct_id = resolver.resolve(name=name, domain=domain, email=reporter)

        rows.append({
            "id": str(issue["id"]),
            "account_id": acct_id,
            "title": issue.get("title") or issue.get("subject"),
            "status": issue.get("status"),
            "priority": issue.get("priority"),
            "category": issue.get("category") or issue.get("type"),
            "assignee_name": (issue.get("assignee") or {}).get("name"),
            "reporter_email": reporter,
            "created_at": issue.get("created_at") or issue.get("createdAt"),
            "resolved_at": issue.get("resolved_at") or issue.get("resolvedAt"),
            "raw": issue,
            "synced_at": _now(),
        })

    if rows:
        for i in range(0, len(rows), 200):
            sb.table("pylon_issues").upsert(rows[i:i+200], on_conflict="id").execute()
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
