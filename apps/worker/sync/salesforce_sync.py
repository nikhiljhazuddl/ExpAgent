"""Salesforce → Supabase sync.

Key feature: dynamically discovers ALL fields on Account, Opportunity, Contact
objects via the SF Describe API — no hard-coded field lists. Every field
lands in the `sf_*_raw` tables as JSONB, and selected fields are promoted to
the typed `sf_accounts` / `sf_opportunities` / `sf_contacts` columns and to
the canonical `accounts` / `people` tables.
"""

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
log = logging.getLogger("sf_sync")

# Fields we always want in the typed summary tables (subset of all fields)
ACCOUNT_TYPED = {
    "Id", "Name", "Website", "Industry", "AnnualRevenue", "NumberOfEmployees",
    "BillingCountry", "BillingCity", "Type", "Description",
}
OPP_TYPED = {
    "Id", "AccountId", "Name", "StageName", "Amount", "CloseDate", "Type",
    "Probability", "ForecastCategory", "LeadSource", "Description",
}
CONTACT_TYPED = {
    "Id", "AccountId", "FirstName", "LastName", "Title", "Email", "Phone",
    "MailingCountry", "Department", "LeadSource",
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def sf_login() -> tuple[str, str]:
    """Returns (instance_url, access_token).

    Tries flows in order:
      1. Client Credentials  — for External Connected Apps (preferred)
      2. Username-Password   — for Internal Connected Apps (fallback)
    """
    login_url = os.environ.get("SF_LOGIN_URL", "https://login.salesforce.com")
    client_id     = os.environ["SF_CLIENT_ID"]
    client_secret = os.environ["SF_CLIENT_SECRET"]

    # ── Flow 1: Client Credentials (External App) ──────────────────────────
    resp = httpx.post(
        f"{login_url}/services/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    if resp.status_code == 200:
        d = resp.json()
        log.info("sf auth: client_credentials flow ✓")
        return d["instance_url"], d["access_token"]

    log.warning("sf client_credentials failed (%s) — trying username-password", resp.status_code)

    # ── Flow 2: Username-Password (Internal App fallback) ──────────────────
    resp = httpx.post(
        f"{login_url}/services/oauth2/token",
        data={
            "grant_type":    "password",
            "client_id":     client_id,
            "client_secret": client_secret,
            "username":      os.environ["SF_USERNAME"],
            "password":      os.environ["SF_PASSWORD"] + os.environ.get("SF_SECURITY_TOKEN", ""),
        },
        timeout=30,
    )
    resp.raise_for_status()
    d = resp.json()
    log.info("sf auth: username-password flow ✓")
    return d["instance_url"], d["access_token"]


# ── Describe — discover ALL fields ────────────────────────────────────────────

def describe_object(instance_url: str, token: str, sobject: str) -> list[str]:
    """Return every queryable field name for a Salesforce object."""
    r = httpx.get(
        f"{instance_url}/services/data/v59.0/sobjects/{sobject}/describe",
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    r.raise_for_status()
    fields: list[str] = []
    for f in r.json().get("fields", []):
        # Skip compound fields (Address, Name) and non-queryable types
        if not f.get("deprecatedAndHidden", False) and f.get("type") not in (
            "address", "location",
        ):
            fields.append(f["name"])
    log.info("sf describe %s → %d fields", sobject, len(fields))
    return fields


# ── SOQL helpers ──────────────────────────────────────────────────────────────

MAX_SOQL_FIELDS = 80    # Keep URL length under Salesforce's ~16KB limit

def _chunk_fields(fields: list[str], base_fields: set[str]) -> list[list[str]]:
    """
    Split fields into batches ≤ MAX_SOQL_FIELDS.
    Always include Id in every batch (for joining).
    """
    priority = ["Id"] + sorted(base_fields - {"Id"})
    rest = [f for f in fields if f not in set(priority)]
    # Batch: first batch = priority + as many rest as fit
    batches: list[list[str]] = []
    current = list(priority)
    for f in rest:
        if len(current) >= MAX_SOQL_FIELDS:
            batches.append(current)
            current = ["Id"]
        current.append(f)
    if current:
        batches.append(current)
    return batches


import re as _re

_BAD_FIELD_RE = _re.compile(r"No such column '([^']+)'")

def soql_query(instance_url: str, token: str, query: str) -> list[dict]:
    """Run a SOQL query, automatically removing inaccessible fields on INVALID_FIELD errors."""
    records: list[dict] = []
    headers = {"Authorization": f"Bearer {token}"}
    base_url = f"{instance_url}/services/data/v59.0/query"
    current_query = query

    # Retry loop for field-level security errors
    for _attempt in range(50):  # max 50 bad-field removals
        url = base_url
        params: dict = {"q": current_query}
        page_records: list[dict] = []
        try:
            while True:
                r = httpx.get(url, headers=headers, params=params, timeout=120)
                if not r.is_success:
                    err_body = r.text
                    m = _BAD_FIELD_RE.search(err_body)
                    if m and r.status_code == 400:
                        bad = m.group(1)
                        log.warning("sf: removing inaccessible field '%s' from query", bad)
                        # Remove the bad field from the SELECT clause
                        current_query = _re.sub(
                            rf"\b{_re.escape(bad)}\b,?\s*", "", current_query
                        ).strip().rstrip(",")
                        # Clean up dangling comma after SELECT
                        current_query = _re.sub(r"SELECT\s+,", "SELECT ", current_query)
                        current_query = _re.sub(r",\s*FROM\b", " FROM", current_query)
                        break  # restart with cleaned query
                    log.error("SF query error %s: %s", r.status_code, err_body[:500])
                    r.raise_for_status()
                data = r.json()
                page_records.extend(data.get("records", []))
                nxt = data.get("nextRecordsUrl")
                if not nxt:
                    return records + page_records  # success
                url = f"{instance_url}{nxt}"
                params = {}
        except Exception:
            raise
    return records + page_records


def _clean(record: dict) -> dict:
    """Strip Salesforce metadata noise from a record."""
    return {k: v for k, v in record.items() if k != "attributes" and not isinstance(v, dict)}


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── Per-object syncs ──────────────────────────────────────────────────────────

def sync_accounts(
    sb: Client, resolver: AccountResolver,
    instance_url: str, token: str,
    all_fields: list[str],
) -> None:
    batches = _chunk_fields(all_fields, ACCOUNT_TYPED)
    # First batch: get everything we need for typed columns + Id
    first_batch = batches[0]
    query = f"SELECT {', '.join(first_batch)} FROM Account WHERE IsDeleted = false"
    records = soql_query(instance_url, token, query)
    log.info("sf: fetched %d accounts (batch 1 / %d fields)", len(records), len(first_batch))

    # Remaining batches: fetch Id + extra fields, merge by Id
    id_to_extra: dict[str, dict] = {r["Id"]: {} for r in records}
    for batch in batches[1:]:
        extra_query = f"SELECT {', '.join(batch)} FROM Account WHERE IsDeleted = false"
        extra_records = soql_query(instance_url, token, extra_query)
        for er in extra_records:
            sf_id = er.get("Id")
            if sf_id in id_to_extra:
                id_to_extra[sf_id].update(_clean(er))
        log.info("sf: merged extra batch of %d fields", len(batch))

    # ── Step 1: Bulk-upsert into canonical `accounts` table by sf_id ──────────
    # This is fast: one upsert per 250 rows, no per-row resolver calls.
    # We use sf_id as the conflict key so re-runs are idempotent.
    WRITE_CHUNK = 250
    acct_rows: list[dict] = []
    for r in records:
        sf_id = r["Id"]
        full: dict[str, Any] = {**_clean(r), **id_to_extra.get(sf_id, {})}
        domain = normalise_domain(r.get("Website"))
        owner_name = None
        if isinstance(r.get("Owner"), dict):
            owner_name = r["Owner"].get("Name")
        row: dict = {
            "sf_id": sf_id,
            "name": r.get("Name") or sf_id,
        }
        if domain:
            row["domain"] = domain
            row["email_domain"] = domain
        if owner_name:
            row["owner_name"] = owner_name
        if r.get("Industry"):
            row["industry"] = r["Industry"]
        acct_rows.append((sf_id, domain, r.get("Name"), owner_name, r.get("Industry"), full))

    # Deduplicate domains — unique constraint means only one account can own a domain.
    # Pre-load ALL existing domains from DB (paginated — default limit is 1000).
    seen_domains: set[str] = set()
    _offset = 0
    while True:
        existing_domain_r = (sb.table("accounts").select("domain")
                             .not_.is_("domain", "null")
                             .range(_offset, _offset + 999).execute())
        for row in (existing_domain_r.data or []):
            if row.get("domain"):
                seen_domains.add(row["domain"])
        if len(existing_domain_r.data or []) < 1000:
            break
        _offset += 1000
    log.info("sf: pre-loaded %d existing domains to skip duplicates", len(seen_domains))

    log.info("sf: bulk-upserting %d rows into accounts table…", len(acct_rows))
    for i in range(0, len(acct_rows), WRITE_CHUNK):
        chunk = acct_rows[i:i + WRITE_CHUNK]
        rows_to_upsert = []
        for sf_id, dom, name, own, ind, _ in chunk:
            row: dict = {"sf_id": sf_id, "name": name or sf_id}
            if dom and dom not in seen_domains:
                row["domain"] = dom
                row["email_domain"] = dom
                seen_domains.add(dom)
            if own:
                row["owner_name"] = own
            if ind:
                row["industry"] = ind
            rows_to_upsert.append(row)
        sb.table("accounts").upsert(rows_to_upsert, on_conflict="sf_id").execute()

    log.info("sf: accounts table updated — fetching back account_id mappings…")

    # ── Step 2: Fetch sf_id → account UUID mapping back in bulk ────────────
    # Read back in pages so we can link sf_accounts / sf_accounts_raw correctly
    sf_id_to_uid: dict[str, str] = {}
    offset = 0
    while True:
        r2 = sb.table("accounts").select("id, sf_id").not_.is_("sf_id", "null") \
            .range(offset, offset + 999).execute()
        for row in (r2.data or []):
            sf_id_to_uid[row["sf_id"]] = row["id"]
        if len(r2.data or []) < 1000:
            break
        offset += 1000
    log.info("sf: loaded %d sf_id→uuid mappings", len(sf_id_to_uid))

    # ── Step 3: Bulk-upsert sf_accounts + sf_accounts_raw ──────────────────
    typed_rows: list[dict] = []
    raw_rows: list[dict] = []
    for sf_id, domain, name, owner_name, industry, full in acct_rows:
        uid = sf_id_to_uid.get(sf_id)
        typed_rows.append({
            "sf_id": sf_id, "account_id": uid,
            "name": name, "industry": industry,
            "annual_revenue": full.get("AnnualRevenue"),
            "number_of_employees": full.get("NumberOfEmployees"),
            "owner_name": owner_name,
            "raw": full,
            "synced_at": _now(),
        })
        raw_rows.append({
            "sf_id": sf_id, "account_id": uid,
            "data": full,
            "synced_at": _now(),
        })

    for i in range(0, len(typed_rows), WRITE_CHUNK):
        # sf_accounts table dropped — raw only
        sb.table("sf_accounts_raw").upsert(raw_rows[i:i + WRITE_CHUNK], on_conflict="sf_id").execute()
        log.info("sf: upserted accounts %d–%d / %d", i + 1, min(i + WRITE_CHUNK, len(typed_rows)), len(typed_rows))

    log.info("sf: upserted %d accounts total", len(records))


def sync_opportunities(
    sb: Client, resolver: AccountResolver,
    instance_url: str, token: str,
    all_fields: list[str],
) -> None:
    batches = _chunk_fields(all_fields, OPP_TYPED)
    records = soql_query(
        instance_url, token,
        f"SELECT {', '.join(batches[0])} FROM Opportunity WHERE IsDeleted = false",
    )
    log.info("sf: fetched %d opportunities", len(records))

    id_to_extra: dict[str, dict] = {r["Id"]: {} for r in records}
    for batch in batches[1:]:
        for er in soql_query(instance_url, token,
                             f"SELECT {', '.join(batch)} FROM Opportunity WHERE IsDeleted = false"):
            sf_id = er.get("Id")
            if sf_id in id_to_extra:
                id_to_extra[sf_id].update(_clean(er))

    WRITE_CHUNK = 250
    typed_rows: list[dict] = []
    raw_rows: list[dict] = []
    for r in records:
        sf_id = r["Id"]
        full = {**_clean(r), **id_to_extra.get(sf_id, {})}
        acct_uid = resolver.resolve(sf_id=r.get("AccountId")) if r.get("AccountId") else None
        typed_rows.append({
            "sf_id": sf_id, "account_sf_id": r.get("AccountId"), "account_id": acct_uid,
            "name": r.get("Name"), "stage": r.get("StageName"),
            "amount": r.get("Amount"), "close_date": r.get("CloseDate"), "type": r.get("Type"),
            "raw": full, "synced_at": _now(),
        })
        raw_rows.append({
            "sf_id": sf_id, "account_id": acct_uid,
            "data": full, "synced_at": _now(),
        })

    for i in range(0, len(typed_rows), WRITE_CHUNK):
        # sf_opportunities table dropped — raw only
        sb.table("sf_opportunities_raw").upsert(raw_rows[i:i + WRITE_CHUNK], on_conflict="sf_id").execute()
        log.info("sf: upserted opportunities %d–%d / %d", i + 1, min(i + WRITE_CHUNK, len(typed_rows)), len(typed_rows))

    log.info("sf: upserted %d opportunities total", len(records))


def sync_contacts(
    sb: Client, resolver: AccountResolver,
    instance_url: str, token: str,
    all_fields: list[str],
) -> None:
    batches = _chunk_fields(all_fields, CONTACT_TYPED)
    records = soql_query(
        instance_url, token,
        f"SELECT {', '.join(batches[0])} FROM Contact WHERE IsDeleted = false",
    )
    log.info("sf: fetched %d contacts", len(records))

    id_to_extra: dict[str, dict] = {r["Id"]: {} for r in records}
    for batch in batches[1:]:
        for er in soql_query(instance_url, token,
                             f"SELECT {', '.join(batch)} FROM Contact WHERE IsDeleted = false"):
            sf_id = er.get("Id")
            if sf_id in id_to_extra:
                id_to_extra[sf_id].update(_clean(er))

    # Bulk-fetch AccountId → account UUID mapping (contacts link via AccountId)
    _acct_sf_to_uid: dict[str, str] = {}
    _off = 0
    while True:
        _r = sb.table("accounts").select("id, sf_id").not_.is_("sf_id", "null") \
            .range(_off, _off + 999).execute()
        for row in (_r.data or []):
            _acct_sf_to_uid[row["sf_id"]] = row["id"]
        if len(_r.data or []) < 1000:
            break
        _off += 1000
    log.info("sf: loaded %d account sf_id→uuid for contacts linking", len(_acct_sf_to_uid))

    people_rows: list[dict] = []
    typed_rows: list[dict] = []
    raw_rows: list[dict] = []
    for r in records:
        sf_id = r["Id"]
        full = {**_clean(r), **id_to_extra.get(sf_id, {})}
        acct_uid = _acct_sf_to_uid.get(r.get("AccountId", "")) if r.get("AccountId") else None

        full_name = f"{r.get('FirstName', '')} {r.get('LastName', '')}".strip()
        if full_name or r.get("Email"):
            people_rows.append({
                "account_id": acct_uid,
                "name": full_name,
                "email": r.get("Email"),
                "title": r.get("Title"),
                "phone": r.get("Phone"),
                "in_crm": True,
                "source": "salesforce",
                "sf_contact_id": sf_id,
            })
        typed_rows.append({
            "sf_id": sf_id, "account_sf_id": r.get("AccountId"), "account_id": acct_uid,
            "first_name": r.get("FirstName"), "last_name": r.get("LastName"),
            "title": r.get("Title"), "email": r.get("Email"),
            "raw": full, "synced_at": _now(),
        })
        raw_rows.append({
            "sf_id": sf_id, "account_id": acct_uid,
            "data": full, "synced_at": _now(),
        })

    WRITE_CHUNK = 250
    for i in range(0, len(typed_rows), WRITE_CHUNK):
        # sf_contacts table dropped — raw only
        sb.table("sf_contacts_raw").upsert(raw_rows[i:i + WRITE_CHUNK], on_conflict="sf_id").execute()
        log.info("sf: upserted contacts %d–%d / %d", i + 1, min(i + WRITE_CHUNK, len(typed_rows)), len(typed_rows))

    if people_rows:
        for i in range(0, len(people_rows), 250):
            sb.table("people").upsert(people_rows[i:i+250], on_conflict="sf_contact_id").execute()
    log.info("sf: upserted %d contacts / people total", len(records))


# ── Main entry ────────────────────────────────────────────────────────────────

def run() -> None:
    log.info("salesforce sync starting — discovering all fields…")
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)
    instance_url, token = sf_login()
    log.info("authenticated → %s", instance_url)

    acct_fields  = describe_object(instance_url, token, "Account")
    opp_fields   = describe_object(instance_url, token, "Opportunity")
    cont_fields  = describe_object(instance_url, token, "Contact")

    sync_accounts(sb, resolver, instance_url, token, acct_fields)
    sync_opportunities(sb, resolver, instance_url, token, opp_fields)
    sync_contacts(sb, resolver, instance_url, token, cont_fields)

    log.info("salesforce sync complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run()
