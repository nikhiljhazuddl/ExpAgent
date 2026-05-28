"""Repository — loads AccountNodes from Supabase.

Key design decisions:
- TRIGGER: use_case_gap__c in Salesforce is the sole trigger field.
  Accounts without it are skipped entirely (not triggered).
- FILTER: Only Customer / Renewal accounts (Account_Status__c or Type).
- OWNERSHIP: CSM-centric. AE removed. CSM name sourced from Pylon
  (assignee on the most recent open issue for that account).
  Falls back to CSM_owner__c in Salesforce if no Pylon match.
- CONVERSATIONS: Gong + Fireflies summaries are included in AccountNode
  and flow all the way into the LLM signal output.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

from schemas.account_node import (
    AccountNode,
    ClayContact,
    Contact,
    Conversations,
    IcpPopulation,
    Ownership,
    Signals1P,
    Signals2P,
    Signals3P,
    UsageCounts,
)

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
logger = logging.getLogger(__name__)

# Account_Status__c / Type values that mean "paying customer"
CUSTOMER_STAGES = {"Customer", "Renewal", "customer", "renewal"}

# Opportunity stages that mean "AE already working it" → DQ4
OPEN_OPP_STAGES = {
    "Prospecting", "Qualification", "Needs Analysis", "Value Proposition",
    "Id. Decision Makers", "Perception Analysis", "Proposal/Price Quote",
    "Negotiation/Review",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None

def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except (ValueError, TypeError):
        return None

def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default

def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None

def _norm_name(name: Any) -> str:
    if not name:
        return ""
    return " ".join(str(name).strip().casefold().split())

def _to_15(sf_id: Any) -> Optional[str]:
    if not sf_id:
        return None
    s = str(sf_id).strip()
    return s[:15] if s else None

def _listify(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    s = str(value).strip()
    return [s] if s else []

def _split_raw(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    return [p.strip() for p in str(value).replace(";", ",").split(",") if p.strip()]


# ---------------------------------------------------------------------------
# Data-quality logger
# ---------------------------------------------------------------------------

@dataclass
class DataQualityIssue:
    account_id: Optional[str]
    account_name: Optional[str]
    issue: str
    detail: str

class DataQualityLog:
    def __init__(self) -> None:
        self._issues: list[DataQualityIssue] = []

    def add(self, issue: str, detail: str = "",
            account_id: Optional[str] = None, account_name: Optional[str] = None) -> None:
        self._issues.append(DataQualityIssue(
            account_id=account_id, account_name=account_name, issue=issue, detail=detail
        ))

    @property
    def issues(self) -> list[DataQualityIssue]:
        return list(self._issues)

    def write_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["account_id", "account_name", "issue", "detail"])
            for it in self._issues:
                w.writerow([it.account_id or "", it.account_name or "", it.issue, it.detail])


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class Repository:
    """Builds AccountNodes from Supabase (CSM-centric, Pylon-owned)."""

    def __init__(self, xlsx_path: Any = None) -> None:
        self.dq_log = DataQualityLog()
        self._sb: Optional[Client] = None

    def _client(self) -> Client:
        if self._sb is None:
            self._sb = create_client(
                os.environ["SUPABASE_URL"],
                os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            )
        return self._sb

    # ---- public API --------------------------------------------------------

    def load_accounts(self) -> list[AccountNode]:
        sb = self._client()

        # 1. Load Customer/Renewal accounts that have use_case_gap__c populated
        sf_rows = self._load_sf_accounts(sb)
        logger.info("repository: %d customer/renewal accounts with gap field", len(sf_rows))

        if not sf_rows:
            logger.warning("repository: no accounts found with use_case_gap__c — check SF data")
            return []

        sf_ids = [r["sf_id"] for r in sf_rows]
        account_ids = [r["account_id"] for r in sf_rows if r.get("account_id")]

        # 2. Load all supporting data in bulk
        # NOTE: sf_opportunities_raw and sf_contacts_raw use account_id (UUID), not sf_id
        raw_by_sfid      = self._load_raw(sb, sf_ids)
        opps_by_acct     = self._load_open_opps(sb, account_ids)
        contacts_by_acct = self._load_contacts(sb, account_ids)
        gong_by_account   = self._load_gong(sb, account_ids)
        ff_by_account     = self._load_fireflies(sb, account_ids)
        linear_by_account = self._load_linear(sb, account_ids)
        # Pylon: CSM assignee per account
        csm_by_account    = self._load_pylon_csm(sb, account_ids)
        # SF Users: resolve CSM_owner__c / OwnerId → human name
        self._sf_users    = self._load_sf_users(sb)

        nodes: list[AccountNode] = []
        for row in sf_rows:
            sf_id = row["sf_id"]
            acct_id = row.get("account_id")
            node = self._build_node(
                row,
                raw_by_sfid.get(sf_id, {}),
                opps_by_acct.get(acct_id, []),
                contacts_by_acct.get(acct_id, []),
                linear_by_account.get(acct_id, []),
                gong_by_account.get(acct_id, []),
                ff_by_account.get(acct_id, []),
                csm_by_account.get(acct_id),
            )
            if node:
                nodes.append(node)

        logger.info("repository: built %d AccountNodes", len(nodes))
        return nodes

    # ---- data loaders ------------------------------------------------------

    def _load_sf_accounts(self, sb: Client) -> list[dict]:
        """Load Customer/Renewal accounts WHERE use_case_gap__c is not null.

        Reads from sf_accounts_raw (sf_accounts typed table was dropped).
        Joins to accounts table to get the canonical account_id UUID.
        """
        # Step 1: load all raw SF account data
        all_raw: list[dict] = []
        page, page_size = 0, 500
        while True:
            resp = (
                sb.table("sf_accounts_raw")
                .select("sf_id, data")
                .range(page * page_size, (page + 1) * page_size - 1)
                .execute()
            )
            batch = resp.data or []
            if not batch:
                break
            all_raw.extend(batch)
            if len(batch) < page_size:
                break
            page += 1

        # Step 2: bulk-load sf_id → account UUID mapping from accounts table
        sf_to_uuid: dict[str, str] = {}
        for i in range(0, len(all_raw), 500):
            chunk_ids = [r["sf_id"] for r in all_raw[i:i+500]]
            r2 = sb.table("accounts").select("id, sf_id").in_("sf_id", chunk_ids).execute()
            for row in (r2.data or []):
                sf_to_uuid[row["sf_id"]] = row["id"]

        # Step 3: filter to Customer/Renewal with use_case_gap__c populated
        customer_with_gap = []
        for r in all_raw:
            raw = r.get("data") or {}
            sf_id = r["sf_id"]
            # Customer/Renewal filter
            status    = (_to_str(raw.get("Account_Status__c")) or "").lower()
            acct_type = (_to_str(raw.get("Type")) or "").lower()
            is_customer = "customer" in status or "renewal" in status or \
                          "customer" in acct_type or "renewal" in acct_type
            if not is_customer:
                continue
            # Trigger filter — use_case_gap__c must be populated
            gap = _to_str(raw.get("use_case_gap__c")) or _to_str(raw.get("Use_Case_Gap__c"))
            if not gap:
                continue
            customer_with_gap.append({
                "sf_id":      sf_id,
                "account_id": sf_to_uuid.get(sf_id),
                "name":       _to_str(raw.get("Name")),
                "raw":        raw,
                "_gap":       gap,
            })

        logger.info("repository: %d / %d accounts are Customer/Renewal with gap",
                    len(customer_with_gap), len(all_raw))
        return customer_with_gap

    def _load_raw(self, sb: Client, sf_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(sf_ids), 200):
            chunk = sf_ids[i:i+200]
            resp = sb.table("sf_accounts_raw").select("sf_id, data").in_("sf_id", chunk).execute()
            for r in (resp.data or []):
                out[r["sf_id"]] = r.get("data") or {}
        return out

    def _load_open_opps(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        """Load from sf_opportunities_raw (typed table was dropped).
        Keyed by account_id UUID (not sf_id).
        """
        out: dict[str, list[dict]] = {}
        valid = [a for a in account_ids if a]
        for i in range(0, len(valid), 200):
            chunk = valid[i:i+200]
            resp = (
                sb.table("sf_opportunities_raw")
                .select("sf_id, account_id, data")
                .in_("account_id", chunk)
                .execute()
            )
            for r in (resp.data or []):
                data = r.get("data") or {}
                acct = r.get("account_id")
                row = {
                    "account_id": acct,
                    "name":       data.get("Name"),
                    "stage":      data.get("StageName"),
                    "amount":     data.get("Amount"),
                    "close_date": data.get("CloseDate"),
                }
                out.setdefault(acct, []).append(row)
        return out

    def _load_contacts(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        """Load from sf_contacts_raw (typed table was dropped).
        Keyed by account_id UUID (not sf_id).
        """
        out: dict[str, list[dict]] = {}
        valid = [a for a in account_ids if a]
        for i in range(0, len(valid), 200):
            chunk = valid[i:i+200]
            resp = (
                sb.table("sf_contacts_raw")
                .select("sf_id, account_id, data")
                .in_("account_id", chunk)
                .execute()
            )
            for r in (resp.data or []):
                data = r.get("data") or {}
                acct = r.get("account_id")
                row = {
                    "account_id": acct,
                    "first_name": data.get("FirstName"),
                    "last_name":  data.get("LastName"),
                    "title":      data.get("Title"),
                    "email":      data.get("Email"),
                    "raw":        data,
                }
                out.setdefault(acct, []).append(row)
        return out

    def _load_gong(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        valid = [a for a in account_ids if a]
        for i in range(0, len(valid), 200):
            chunk = valid[i:i+200]
            resp = (
                sb.table("gong_calls")
                .select("account_id, title, started_at, duration_secs, key_points, topics, action_items, highlights")
                .in_("account_id", chunk)
                .order("started_at", desc=True)
                .execute()
            )
            for r in (resp.data or []):
                out.setdefault(r["account_id"], []).append(r)
        return out

    def _load_fireflies(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        valid = [a for a in account_ids if a]
        for i in range(0, len(valid), 200):
            chunk = valid[i:i+200]
            resp = (
                sb.table("fireflies_meetings")
                .select("account_id, title, date, duration_secs, summary, action_items, key_questions, outline")
                .in_("account_id", chunk)
                .order("date", desc=True)
                .execute()
            )
            for r in (resp.data or []):
                out.setdefault(r["account_id"], []).append(r)
        return out

    def _load_sf_users(self, sb: Client) -> dict[str, str]:
        """Bulk-load SF user_id → name lookup for CSM/AE resolution."""
        out: dict[str, str] = {}
        try:
            page = 0
            while True:
                r = sb.table("sf_users").select("id, name").range(page*1000, (page+1)*1000 - 1).execute()
                rows = r.data or []
                for row in rows:
                    if row.get("id") and row.get("name"):
                        out[row["id"]] = row["name"]
                if len(rows) < 1000:
                    break
                page += 1
            logger.info("repository: loaded %d SF user names for CSM/AE resolution", len(out))
        except Exception as e:
            logger.warning("repository: sf_users table missing or unreadable (%s) — CSM IDs will show raw", e)
        return out

    def _load_linear(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        """Return up to 10 most recent Linear issues per account, keyed by account_id UUID."""
        out: dict[str, list[dict]] = {}
        valid = [a for a in account_ids if a]
        for i in range(0, len(valid), 200):
            chunk = valid[i:i+200]
            resp = (
                sb.table("linear_issues")
                .select("account_id, id, title, status, priority, assignee_name, created_at")
                .in_("account_id", chunk)
                .order("created_at", desc=True)
                .execute()
            )
            for r in (resp.data or []):
                acct = r.get("account_id")
                if acct:
                    out.setdefault(acct, []).append(r)
        return out

    def _load_pylon_csm(self, sb: Client, account_ids: list[str]) -> dict[str, Optional[str]]:
        """Return the most recent Pylon assignee name per account — this is the CSM."""
        out: dict[str, Optional[str]] = {}
        valid = [a for a in account_ids if a]
        for i in range(0, len(valid), 200):
            chunk = valid[i:i+200]
            resp = (
                sb.table("pylon_issues")
                .select("account_id, assignee_name, created_at")
                .in_("account_id", chunk)
                .not_.is_("assignee_name", "null")
                .order("created_at", desc=True)
                .execute()
            )
            # Take the most recent assignee per account (first hit per account_id)
            for r in (resp.data or []):
                acct = r["account_id"]
                if acct not in out:
                    out[acct] = r.get("assignee_name")
        return out

    # ---- node builder ------------------------------------------------------

    def _build_node(
        self,
        row: dict,
        raw: dict,
        opps: list[dict],
        contacts: list[dict],
        linear_issues: list[dict],
        gong_calls: list[dict],
        fireflies: list[dict],
        pylon_csm: Optional[str],
    ) -> Optional[AccountNode]:
        sf_id      = row.get("sf_id") or ""
        acct_name  = _to_str(row.get("name")) or "(unknown)"
        aid15      = _to_15(sf_id) or sf_id
        flags: list[str] = []

        # ── Use case gap — the trigger field ──────────────────────────────
        use_case_gap = row.get("_gap") or _to_str(raw.get("use_case_gap__c")) or _to_str(raw.get("Use_Case_Gap__c"))

        # ── CSM ownership (Pylon first, SF fallback) ──────────────────────
        # SF CSM_owner__c is a User Id — resolve to human name via sf_users lookup
        users = getattr(self, "_sf_users", {}) or {}
        sf_csm_id = _to_str(raw.get("CSM_owner__c")) or _to_str(raw.get("CSM_Owner__c"))
        sf_csm_name = users.get(sf_csm_id) if sf_csm_id else None
        # Final fallback: account OwnerId
        owner_id = _to_str(raw.get("OwnerId"))
        owner_name = users.get(owner_id) if owner_id else None
        csm_name = pylon_csm or sf_csm_name or owner_name
        if not csm_name:
            self.dq_log.add("missing_csm", "no Pylon assignee and no SF CSM_owner__c",
                            account_id=aid15, account_name=acct_name)
            flags.append("missing_csm")

        ownership = Ownership(
            ae_name=None,   # AE removed — CSM-centric
            ae_role=None,
            csm_name=csm_name,
            csm_missing=csm_name is None,
        )

        # ── Account state ─────────────────────────────────────────────────
        last_activity_date = _to_date(raw.get("LastActivityDate"))
        plan_end           = _to_date(raw.get("Plan_End_Date__c"))
        latest_exp_end     = _to_date(raw.get("Contract_Period__c"))
        inactive_over_90   = self._is_inactive_90(last_activity_date)
        adoption_health    = _to_str(raw.get("Adoption_Health__c"))
        health_status      = _to_str(raw.get("Health_Status__c"))

        # All accounts here are Customer/Renewal — active by definition
        is_active = True

        # Open expansion opp
        has_open_opp = any(_to_str(o.get("stage")) in OPEN_OPP_STAGES for o in opps)

        # ── Usage rollups from SF custom fields ───────────────────────────
        usage = UsageCounts(
            field_events_all_time      = _to_float(raw.get("Number_of_Field_Events__c")),
            third_party_events_all_time= _to_float(raw.get("No_of_3rd_party_events_year__c")),
            webinars_all_time          = _to_float(raw.get("Number_of_Webinars__c")),
            conferences_all_time       = _to_float(raw.get("Gong__Gong_Count__c")),  # proxy
            standard_in_person=0.0, standard_hybrid=0.0, standard_virtual=0.0,
        )

        # ── Signals ───────────────────────────────────────────────────────
        s1p = Signals1P(
            factors_intent_label     = _to_str(raw.get("Factors_Engagement_Level__c")),
            demo_pricing_visits_90d  = None,
            factors_last_intent_date = _to_str(raw.get("Factors_last_intent_date__c")),
        )
        s3p = Signals3P(
            event_role_hiring_90d      = None,
            competitor_mentions_g2_90d = _to_int(raw.get("G2_Total_Pageviews__c")),
            competitor_in_stack        = _split_raw(raw.get("Competitor_Stack__c")),
        )

        # ── Linear issues ────────────────────────────────────────────────
        # Keep up to 10 most recent; already sorted desc by created_at
        linear_top = linear_issues[:10]

        # ── Conversations (Gong + Fireflies) ──────────────────────────────
        conversations = self._build_conversations(gong_calls, fireflies, acct_name, aid15)

        # ── Contacts from SF ──────────────────────────────────────────────
        sf_contacts = [self._build_sf_contact(c) for c in contacts]
        if not sf_contacts:
            self.dq_log.add("contacts_sf_no_match", f"sf_id={sf_id}",
                            account_id=aid15, account_name=acct_name)

        # ── Profile ───────────────────────────────────────────────────────
        segment = _to_str(raw.get("Account_Segment__c"))
        acv = (_to_float(raw.get("Total_Contract_Value_TCV__c"))
               or _to_float(raw.get("Current_contract_value__c")) or None)

        return AccountNode(
            account_id_18=sf_id,
            account_id_15=aid15,
            account_name=acct_name,
            domain=_to_str(raw.get("Domain__c")) or _to_str(raw.get("Website")),
            ownership=ownership,
            segment=segment,
            acv_usd=acv if acv else None,
            target_departments=[],
            sales_model=None,
            target_customers=[],
            use_case_gap_field=use_case_gap,
            adoption_health=adoption_health,
            last_activity_date=last_activity_date,
            plan_end_date=plan_end,
            latest_expansion_contract_end=latest_exp_end,
            has_open_expansion_opp=has_open_opp,
            is_active_customer=is_active,
            inactive_over_90_days=inactive_over_90,
            health_status=health_status,
            usage=usage,
            signals_1p=s1p,
            signals_2p=Signals2P(),
            signals_3p=s3p,
            icp_population=IcpPopulation(),
            conversations=conversations,
            linear_issues=linear_top,
            contacts_in_product_sf=sf_contacts,
            contacts_not_in_product_clay=[],
            data_quality_flags=flags,
        )

    def _is_inactive_90(self, last_activity: Optional[date]) -> bool:
        if last_activity is None:
            return False
        return (date.today() - last_activity).days > 90

    def _build_conversations(
        self,
        gong_calls: list[dict],
        fireflies: list[dict],
        account_name: str,
        aid15: str,
    ) -> Conversations:
        if not gong_calls and not fireflies:
            self.dq_log.add("gong_fireflies_no_match", f"id15={aid15}",
                            account_id=aid15, account_name=account_name)
            return Conversations()

        # Gong — latest call + aggregate key points across all calls
        gong_summary   = None
        gong_key_points: list[str] = []
        gong_competitors: list[str] = []
        date_range: Optional[str] = None

        if gong_calls:
            latest = gong_calls[0]
            highlights = _listify(latest.get("highlights"))
            gong_summary = highlights[0] if highlights else None
            # Aggregate key points from up to 5 most recent calls
            for call in gong_calls[:5]:
                gong_key_points.extend(_listify(call.get("key_points")))
                gong_competitors.extend(_listify(call.get("topics")))
            gong_key_points  = list(dict.fromkeys(gong_key_points))[:10]  # dedupe
            gong_competitors = list(dict.fromkeys(gong_competitors))[:5]
            if gong_calls[-1].get("started_at") and gong_calls[0].get("started_at"):
                date_range = (f"{gong_calls[-1]['started_at'][:10]}"
                              f" → {gong_calls[0]['started_at'][:10]}")

        # Fireflies — latest meeting + aggregate action items
        ff_overview    = None
        ff_action_items: list[str] = []
        ff_topics: list[str] = []

        if fireflies:
            latest_ff = fireflies[0]
            ff_overview = _to_str(latest_ff.get("summary"))
            for mtg in fireflies[:5]:
                ff_action_items.extend(_listify(mtg.get("action_items")))
                ff_topics.extend(_listify(mtg.get("key_questions")))
            ff_action_items = list(dict.fromkeys(ff_action_items))[:10]
            ff_topics       = list(dict.fromkeys(ff_topics))[:10]

        return Conversations(
            has_gong        = len(gong_calls) > 0,
            has_fireflies   = len(fireflies) > 0,
            total_calls     = len(gong_calls) + len(fireflies),
            date_range      = date_range,
            gong_business_summary     = gong_summary,
            gong_product_interests    = [],
            gong_competitors_mentioned= gong_competitors,
            gong_key_points           = gong_key_points,
            fireflies_overview        = ff_overview,
            fireflies_action_items    = ff_action_items,
            fireflies_topics          = ff_topics,
        )

    def _build_sf_contact(self, c: dict) -> Contact:
        first = _to_str(c.get("first_name")) or ""
        last  = _to_str(c.get("last_name")) or ""
        name  = (first + " " + last).strip() or "(unknown)"
        raw   = c.get("raw") or {}
        return Contact(
            name              = name,
            title             = _to_str(c.get("title")),
            email             = _to_str(c.get("email")),
            linkedin          = _to_str(raw.get("LinkedIn_URL__c")),
            seniority         = None,
            persona           = None,
            persona_fit_score = None,
        )
