"""Linear → Supabase sync (issues).

Linear uses a GraphQL API. We pull all issues and try to map them to
canonical accounts via issue labels, team names, or a custom field
that stores the Zuddl account/customer name.
"""

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
log = logging.getLogger("linear_sync")

LINEAR_ENDPOINT = "https://api.linear.app/graphql"
PRIORITY_MAP = {0: "none", 1: "urgent", 2: "high", 3: "medium", 4: "low"}


def _gql(query: str, variables: dict | None = None) -> dict:
    r = httpx.post(
        LINEAR_ENDPOINT,
        json={"query": query, "variables": variables or {}},
        headers={
            "Authorization": os.environ["LINEAR_API_KEY"],
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


ISSUES_QUERY = """
query Issues($after: String) {
  issues(
    first: 100
    after: $after
    orderBy: updatedAt
  ) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      identifier
      title
      state { name }
      priority
      assignee { name }
      team { name }
      labels { nodes { name } }
      dueDate
      createdAt
      completedAt
      customerTicketCount
      description
    }
  }
}
"""


def _fetch_all_issues() -> list[dict]:
    """Fetch in pages of 100; yield each page so caller can write incrementally."""
    issues: list[dict] = []
    cursor: str | None = None
    while True:
        data = _gql(ISSUES_QUERY, {"after": cursor})
        page = (data.get("data") or {}).get("issues", {})
        batch = page.get("nodes", [])
        issues.extend(batch)
        log.info("linear: fetched %d issues so far", len(issues))
        if not page.get("pageInfo", {}).get("hasNextPage"):
            break
        cursor = page["pageInfo"]["endCursor"]
    return issues


def _resolve_account(issue: dict, resolver: AccountResolver) -> str | None:
    """Heuristic: look for a label or team that matches a known account name/domain."""
    labels = [n["name"] for n in (issue.get("labels") or {}).get("nodes", [])]
    # Labels that look like customer names (common convention: "customer: CrowdStrike")
    for label in labels:
        if label.lower().startswith("customer:"):
            name = label.split(":", 1)[1].strip()
            if name:
                return resolver.resolve(name=name)
        # Or plain customer name label
        result = resolver.resolve(name=label)
        if result:
            return result
    return None


def _now() -> str:
    return datetime.utcnow().isoformat()


def sync(sb: Client, resolver: AccountResolver) -> None:
    issues = _fetch_all_issues()
    log.info("linear: %d issues to process", len(issues))

    total = 0
    # Write in batches of 50 to avoid Supabase timeouts on large orgs
    batch: list[dict] = []
    for issue in issues:
        acct_id = _resolve_account(issue, resolver)
        batch.append({
            "id": issue["id"],
            "account_id": acct_id,
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "status": (issue.get("state") or {}).get("name"),
            "priority": issue.get("priority"),
            "assignee_name": (issue.get("assignee") or {}).get("name"),
            "team_name": (issue.get("team") or {}).get("name"),
            "labels": [n["name"] for n in (issue.get("labels") or {}).get("nodes", [])],
            "due_date": issue.get("dueDate"),
            "created_at": issue.get("createdAt"),
            "completed_at": issue.get("completedAt"),
            "raw": {
                "description": issue.get("description"),
                "customerTicketCount": issue.get("customerTicketCount"),
            },
            "synced_at": _now(),
        })
        if len(batch) >= 50:
            sb.table("linear_issues").upsert(batch, on_conflict="id").execute()
            total += len(batch)
            log.info("linear: written %d / %d", total, len(issues))
            batch = []

    if batch:
        sb.table("linear_issues").upsert(batch, on_conflict="id").execute()
        total += len(batch)

    log.info("linear: upserted %d issues", total)


def run() -> None:
    log.info("linear sync starting…")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)
    sync(sb, resolver)
    log.info("linear sync done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
