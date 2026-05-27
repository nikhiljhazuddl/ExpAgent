"""HubSpot → Supabase sync (Companies, Contacts, Deals)."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

from sync.account_resolver import AccountResolver, normalise_domain

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("hs_sync")

HS_BASE = "https://api.hubapi.com"


def _headers() -> dict:
    key = os.environ["HUBSPOT_API_KEY"]
    # Support both legacy hapikey and modern Bearer tokens
    if key.startswith("pat-"):
        return {"Authorization": f"Bearer {key}"}
    return {"Authorization": f"Bearer {key}"}   # hapikey also works as Bearer in v3


def _paginate(path: str, params: dict | None = None) -> list[dict]:
    """Page through HubSpot CRM list endpoint."""
    results: list[dict] = []
    url = f"{HS_BASE}{path}"
    p = dict(params or {})
    p.setdefault("limit", 100)
    while True:
        r = httpx.get(url, headers=_headers(), params=p, timeout=60)
        if r.status_code == 401:
            # retry with hapikey query param (legacy key format)
            r = httpx.get(url, params={**p, "hapikey": os.environ["HUBSPOT_API_KEY"]}, timeout=60)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("results", []))
        after = (data.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
        p["after"] = after
    return results


def _prop(obj: dict, key: str) -> Any:
    return (obj.get("properties") or {}).get(key)


def _now() -> str:
    return datetime.utcnow().isoformat()


def sync(sb: Client, resolver: AccountResolver) -> None:
    # ── Companies ──
    companies = _paginate("/crm/v3/objects/companies", {
        "properties": "name,domain,industry,annualrevenue,lifecyclestage,hubspot_owner_id,hs_object_id"
    })
    for c in companies:
        hs_id = c["id"]
        name = _prop(c, "name")
        domain = normalise_domain(_prop(c, "domain"))
        uid = resolver.resolve(
            name=name, domain=domain, hubspot_id=hs_id,
            extra_fields={"industry": _prop(c, "industry")},
        )
        # patch canonical account with hubspot_id if missing
        sb.table("accounts").update({"hubspot_id": hs_id}).eq("id", uid).is_("hubspot_id", "null").execute()
        sb.table("hubspot_companies").upsert({
            "hs_id": hs_id, "account_id": uid,
            "name": name, "domain": domain,
            "industry": _prop(c, "industry"),
            "arr": _prop(c, "annualrevenue"),
            "lifecycle_stage": _prop(c, "lifecyclestage"),
            "raw": c.get("properties", {}),
            "synced_at": _now(),
        }, on_conflict="hs_id").execute()
    log.info("hs: synced %d companies", len(companies))

    # ── Contacts ──
    contacts = _paginate("/crm/v3/objects/contacts", {
        "properties": "firstname,lastname,email,jobtitle,associatedcompanyid"
    })
    for c in contacts:
        hs_id = c["id"]
        email = _prop(c, "email")
        name = f"{_prop(c, 'firstname') or ''} {_prop(c, 'lastname') or ''}".strip()
        uid = resolver.resolve(email=email, hubspot_id=None)
        sb.table("hubspot_contacts").upsert({
            "hs_id": hs_id, "account_id": uid,
            "first_name": _prop(c, "firstname"), "last_name": _prop(c, "lastname"),
            "email": email, "title": _prop(c, "jobtitle"),
            "raw": c.get("properties", {}),
            "synced_at": _now(),
        }, on_conflict="hs_id").execute()
        if email or name:
            sb.table("people").upsert({
                "account_id": uid, "name": name, "email": email,
                "title": _prop(c, "jobtitle"),
                "in_crm": True, "source": "hubspot",
                "hubspot_contact_id": hs_id,
            }, on_conflict="hubspot_contact_id").execute()
    log.info("hs: synced %d contacts", len(contacts))

    # ── Deals ──
    deals = _paginate("/crm/v3/objects/deals", {
        "properties": "dealname,dealstage,amount,closedate,dealtype,associations"
    })
    for d in deals:
        hs_id = d["id"]
        sb.table("hubspot_deals").upsert({
            "hs_id": hs_id, "account_id": None,   # association lookup skipped for speed
            "name": _prop(d, "dealname"), "stage": _prop(d, "dealstage"),
            "amount": _prop(d, "amount"), "close_date": _prop(d, "closedate"),
            "deal_type": _prop(d, "dealtype"),
            "raw": d.get("properties", {}),
            "synced_at": _now(),
        }, on_conflict="hs_id").execute()
    log.info("hs: synced %d deals", len(deals))


def run() -> None:
    log.info("hubspot sync starting…")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)
    sync(sb, resolver)
    log.info("hubspot sync done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
