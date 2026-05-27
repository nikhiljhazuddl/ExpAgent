"""Canonical account resolver.

Universal matching keys (in priority order):
  1. domain        — normalised website domain  e.g. crowdstrike.com
  2. email_domain  — extracted from a contact email  @crowdstrike.com → crowdstrike.com
  3. name          — case-insensitive exact match, then strip common suffixes

sf_id / hubspot_id are used as SECONDARY hints to FIND an existing row, never
as the primary create key — because Gong, Fireflies, Pylon, Linear have no
Salesforce IDs, they only know company names and email domains.

Creates a new accounts row if nothing matches.
"""

from __future__ import annotations

import re
import logging
from typing import Optional

from supabase import Client

log = logging.getLogger("resolver")

_STRIP_URL = re.compile(r"^(https?://)?(www\.)?", re.I)
_STRIP_PATH = re.compile(r"/.*$")
# Common company suffixes to normalise for name matching
_COMPANY_SUFFIXES = re.compile(
    r"\s+(inc\.?|llc\.?|ltd\.?|limited|corp\.?|corporation|co\.?|gmbh|pvt\.?|private)$",
    re.I,
)


def normalise_domain(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    d = _STRIP_URL.sub("", raw.strip().lower())
    d = _STRIP_PATH.sub("", d).strip()
    # strip trailing dot
    d = d.rstrip(".")
    return d or None


def email_to_domain(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    return normalise_domain(email.split("@", 1)[1])


def normalise_name(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    n = _COMPANY_SUFFIXES.sub("", name.strip())
    return n.strip().lower()


# Domains that should NEVER be used as account identifiers
INTERNAL_DOMAINS = {
    "zuddl.com", "gmail.com", "googlemail.com",
    "outlook.com", "hotmail.com", "yahoo.com",
    "icloud.com", "me.com", "mac.com",
}


class AccountResolver:
    """Stateful resolver that caches domain/name → uuid for one sync run."""

    def __init__(self, sb: Client) -> None:
        self.sb = sb
        # cache: normalised_domain OR "name:<normalised_name>" → account uuid
        self._cache: dict[str, str] = {}

    # ── public API ────────────────────────────────────────────────────────────

    def resolve(
        self,
        *,
        name: Optional[str] = None,
        domain: Optional[str] = None,
        email: Optional[str] = None,
        sf_id: Optional[str] = None,
        hubspot_id: Optional[str] = None,
        extra_fields: Optional[dict] = None,
    ) -> Optional[str]:
        """Return canonical account UUID, creating a row if needed.

        Returns None only if there is truly nothing to match on.
        """
        dom = normalise_domain(domain)
        if not dom:
            dom = email_to_domain(email)
        # Reject internal / generic domains
        if dom and dom in INTERNAL_DOMAINS:
            dom = None

        norm_name = normalise_name(name)

        # ── 1. cache hit ──
        if dom and dom in self._cache:
            return self._cache[dom]
        if norm_name and f"name:{norm_name}" in self._cache:
            return self._cache[f"name:{norm_name}"]

        # ── 2. DB lookup: domain (fastest, most reliable) ──
        if dom:
            uid = self._db_by_domain(dom)
            if uid:
                self._cache[dom] = uid
                if norm_name:
                    self._cache[f"name:{norm_name}"] = uid
                return uid

        # ── 3. DB lookup: sf_id ──
        if sf_id:
            uid = self._db_by_col("sf_id", sf_id)
            if uid:
                if dom:
                    self._cache[dom] = uid
                if norm_name:
                    self._cache[f"name:{norm_name}"] = uid
                return uid

        # ── 4. DB lookup: hubspot_id ──
        if hubspot_id:
            uid = self._db_by_col("hubspot_id", hubspot_id)
            if uid:
                if dom:
                    self._cache[dom] = uid
                if norm_name:
                    self._cache[f"name:{norm_name}"] = uid
                return uid

        # ── 5. DB lookup: name (case-insensitive) ──
        if norm_name:
            uid = self._db_by_name(name)  # type: ignore[arg-type]
            if uid:
                if dom:
                    self._cache[dom] = uid
                self._cache[f"name:{norm_name}"] = uid
                # patch domain onto account if we now have it
                if dom:
                    self.sb.table("accounts").update({"domain": dom, "email_domain": dom}) \
                        .eq("id", uid).is_("domain", "null").execute()
                return uid

        # ── 6. Nothing matched — bail if no identity ──
        if not name and not dom:
            return None

        # ── 7. Create new canonical account ──
        uid = self._create(
            name=name or dom or "Unknown",
            domain=dom,
            sf_id=sf_id,
            hubspot_id=hubspot_id,
            extra=extra_fields or {},
        )
        if dom:
            self._cache[dom] = uid
        if norm_name:
            self._cache[f"name:{norm_name}"] = uid
        return uid

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _db_by_domain(self, domain: str) -> Optional[str]:
        r = (self.sb.table("accounts")
             .select("id")
             .eq("domain", domain)
             .limit(1)
             .execute())
        rows = r.data or []
        return rows[0]["id"] if rows else None

    def _db_by_col(self, col: str, val: str) -> Optional[str]:
        r = (self.sb.table("accounts")
             .select("id")
             .eq(col, val)
             .limit(1)
             .execute())
        rows = r.data or []
        return rows[0]["id"] if rows else None

    def _db_by_name(self, name: str) -> Optional[str]:
        # exact case-insensitive
        r = (self.sb.table("accounts")
             .select("id")
             .ilike("name", name.strip())
             .limit(1)
             .execute())
        rows = r.data or []
        if rows:
            return rows[0]["id"]
        # try stripping suffixes  e.g. "CrowdStrike Inc" matches "CrowdStrike"
        norm = normalise_name(name)
        if norm and norm != name.strip().lower():
            r2 = (self.sb.table("accounts")
                  .select("id")
                  .ilike("name", f"{norm}%")
                  .limit(1)
                  .execute())
            rows2 = r2.data or []
            if rows2:
                return rows2[0]["id"]
        return None

    def _create(
        self,
        name: str,
        domain: Optional[str],
        sf_id: Optional[str],
        hubspot_id: Optional[str],
        extra: dict,
    ) -> str:
        payload: dict = {"name": name}
        if domain:
            payload["domain"] = domain
            payload["email_domain"] = domain
        if sf_id:
            payload["sf_id"] = sf_id
        if hubspot_id:
            payload["hubspot_id"] = hubspot_id
        payload.update({k: v for k, v in extra.items() if v not in (None, "")})
        r = self.sb.table("accounts").insert(payload).execute()
        uid = r.data[0]["id"]
        log.info("created canonical account '%s' (domain=%s) → %s", name, domain, uid)
        return uid
