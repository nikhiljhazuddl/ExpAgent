"""Repository — loads AccountNodes from Supabase (replaces xlsx reader).

Authoritative filter: Account_Status__c IN ('Customer', 'Renewal') on sf_accounts.
These are the only accounts eligible for expansion — we never load prospects or
churned accounts into the agent pipeline.

Join strategy (mirrors the old xlsx sheet joins):
  sf_accounts        → identity, ownership, current state, usage flags
  sf_accounts_raw    → full raw JSONB for extra fields not in typed columns
  sf_contacts        → contacts in product / CRM (replaces Contacts_From_SF sheet)
  sf_opportunities   → open expansion opp detection (replaces Account-Data col 196)
  gong_calls         → Gong conversation summaries (replaces Gong sheet)
  fireflies_meetings → Fireflies conversation summaries (replaces Fireflies sheet)

The LangGraph nodes receive the same list[AccountNode] as before — zero changes
needed upstream.
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

# Salesforce Account_Status__c values we consider "expansion-eligible"
CUSTOMER_STAGES = {"Customer", "Renewal", "customer", "renewal"}

# Opportunity stages that mean "already being worked" → DQ4
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


def _bool_val(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    return str(value).strip().casefold() in {"1", "true", "yes", "y"}


def _norm_name(name: Any) -> str:
    if not name:
        return ""
    return " ".join(str(name).strip().casefold().split())


def _to_15(sf_id: Any) -> Optional[str]:
    if not sf_id:
        return None
    s = str(sf_id).strip()
    return s[:15] if s else None


# ---------------------------------------------------------------------------
# Data-quality logger (same interface as before)
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
    """Builds AccountNodes from Supabase.

    Lifecycle (unchanged from xlsx version):
        repo = Repository()
        nodes = repo.load_accounts()   # returns list[AccountNode] — Customer/Renewal only
        repo.dq_log.write_csv(...)
    """

    def __init__(self, xlsx_path: Any = None) -> None:
        # xlsx_path accepted but ignored — kept so graph/nodes.py doesn't need changes
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

        # 1. Load Customer/Renewal SF accounts only
        sf_rows = self._load_sf_accounts(sb)
        logger.info("repository: %d customer/renewal accounts loaded from Supabase", len(sf_rows))

        if not sf_rows:
            logger.warning("repository: no customer accounts found — check Account_Status__c filter")
            return []

        # Build lookup maps keyed by sf_id
        sf_ids = [r["sf_id"] for r in sf_rows]
        account_ids = [r["account_id"] for r in sf_rows if r.get("account_id")]

        # 2. Load supporting data in bulk
        raw_by_sfid = self._load_raw(sb, sf_ids)
        opps_by_sfid = self._load_open_opps(sb, sf_ids)
        contacts_by_account = self._load_contacts(sb, sf_ids)
        gong_by_account = self._load_gong(sb, account_ids)
        fireflies_by_account = self._load_fireflies(sb, account_ids)

        nodes: list[AccountNode] = []
        for row in sf_rows:
            node = self._build_node(
                row,
                raw_by_sfid.get(row["sf_id"], {}),
                opps_by_sfid.get(row["sf_id"], []),
                contacts_by_account.get(row["sf_id"], []),
                gong_by_account.get(row.get("account_id"), []),
                fireflies_by_account.get(row.get("account_id"), []),
            )
            if node:
                nodes.append(node)

        logger.info("repository: built %d AccountNodes", len(nodes))
        return nodes

    # ---- data loaders ------------------------------------------------------

    def _load_sf_accounts(self, sb: Client) -> list[dict]:
        """Load only Customer/Renewal accounts from sf_accounts."""
        all_rows: list[dict] = []
        # Supabase REST filters on a JSONB path for Account_Status__c
        # We try the typed `raw` JSONB column for the status field
        # Pull all and filter in Python (cleaner than JSONB path queries via REST)
        page = 0
        page_size = 500
        while True:
            resp = (
                sb.table("sf_accounts")
                .select("sf_id, account_id, name, industry, annual_revenue, number_of_employees, owner_name, raw, synced_at")
                .range(page * page_size, (page + 1) * page_size - 1)
                .execute()
            )
            batch = resp.data or []
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
            page += 1

        # Filter: Account_Status__c OR Type OR Stage__c must indicate customer
        customer_rows = []
        for r in all_rows:
            raw = r.get("raw") or {}
            status = _to_str(raw.get("Account_Status__c")) or ""
            acct_type = _to_str(raw.get("Type")) or ""
            stage = _to_str(raw.get("Stage__c")) or ""
            is_customer = (
                status in CUSTOMER_STAGES
                or acct_type in CUSTOMER_STAGES
                or stage in CUSTOMER_STAGES
                or "customer" in status.lower()
                or "renewal" in status.lower()
            )
            if is_customer:
                customer_rows.append(r)

        logger.info("repository: %d / %d accounts are Customer/Renewal", len(customer_rows), len(all_rows))
        return customer_rows

    def _load_raw(self, sb: Client, sf_ids: list[str]) -> dict[str, dict]:
        """Load full raw JSONB from sf_accounts_raw, keyed by sf_id."""
        out: dict[str, dict] = {}
        for i in range(0, len(sf_ids), 200):
            chunk = sf_ids[i:i+200]
            resp = sb.table("sf_accounts_raw").select("sf_id, data").in_("sf_id", chunk).execute()
            for r in (resp.data or []):
                out[r["sf_id"]] = r.get("data") or {}
        return out

    def _load_open_opps(self, sb: Client, sf_ids: list[str]) -> dict[str, list[dict]]:
        """Load open opportunities per account sf_id."""
        out: dict[str, list[dict]] = {}
        for i in range(0, len(sf_ids), 200):
            chunk = sf_ids[i:i+200]
            resp = (
                sb.table("sf_opportunities")
                .select("account_sf_id, name, stage, amount, close_date, raw")
                .in_("account_sf_id", chunk)
                .execute()
            )
            for r in (resp.data or []):
                key = r["account_sf_id"]
                out.setdefault(key, []).append(r)
        return out

    def _load_contacts(self, sb: Client, sf_ids: list[str]) -> dict[str, list[dict]]:
        """Load SF contacts per account sf_id."""
        out: dict[str, list[dict]] = {}
        for i in range(0, len(sf_ids), 200):
            chunk = sf_ids[i:i+200]
            resp = (
                sb.table("sf_contacts")
                .select("account_sf_id, first_name, last_name, title, email, raw")
                .in_("account_sf_id", chunk)
                .execute()
            )
            for r in (resp.data or []):
                key = r["account_sf_id"]
                out.setdefault(key, []).append(r)
        return out

    def _load_gong(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        """Load Gong calls per canonical account_id."""
        out: dict[str, list[dict]] = {}
        valid_ids = [a for a in account_ids if a]
        for i in range(0, len(valid_ids), 200):
            chunk = valid_ids[i:i+200]
            resp = (
                sb.table("gong_calls")
                .select("account_id, title, date, duration_secs, summary, key_points, topics, action_items, parties_companies")
                .in_("account_id", chunk)
                .order("date", desc=True)
                .execute()
            )
            for r in (resp.data or []):
                out.setdefault(r["account_id"], []).append(r)
        return out

    def _load_fireflies(self, sb: Client, account_ids: list[str]) -> dict[str, list[dict]]:
        """Load Fireflies meetings per canonical account_id."""
        out: dict[str, list[dict]] = {}
        valid_ids = [a for a in account_ids if a]
        for i in range(0, len(valid_ids), 200):
            chunk = valid_ids[i:i+200]
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

    # ---- node builder ------------------------------------------------------

    def _build_node(
        self,
        row: dict,
        raw: dict,
        opps: list[dict],
        contacts: list[dict],
        gong_calls: list[dict],
        fireflies_meetings: list[dict],
    ) -> Optional[AccountNode]:
        sf_id = row.get("sf_id")
        account_name = _to_str(row.get("name")) or "(unknown)"
        flags: list[str] = []

        # IDs — use sf_id as the 18-char ID, truncate to 15
        aid18 = sf_id or ""
        aid15 = _to_15(aid18) or aid18

        # Ownership from raw SF data
        ae_name = _to_str(raw.get("Owner", {}).get("Name") if isinstance(raw.get("Owner"), dict) else None) \
                  or _to_str(row.get("owner_name"))
        csm_name = _to_str(raw.get("CSM_owner__c"))
        ownership = Ownership(
            ae_name=ae_name,
            ae_role=_to_str(raw.get("Owner_Role__c")),
            csm_name=csm_name,
            csm_missing=csm_name is None,
        )
        if csm_name is None:
            self.dq_log.add("missing_csm", "routing to AE only", account_id=aid15, account_name=account_name)
            flags.append("missing_csm")

        # Current state
        adoption_health = _to_str(raw.get("Adoption_Health__c"))  # if exists in SF
        use_case_gap = _to_str(raw.get("Use_Case_2025__c")) or _to_str(raw.get("If_not_an_ICP__c"))
        last_activity_date = _to_date(raw.get("LastActivityDate"))
        plan_end = _to_date(raw.get("Plan_End_Date__c"))
        latest_exp_end = _to_date(raw.get("Contract_Period__c"))
        inactive_over_90 = self._is_inactive_90(last_activity_date)

        # Is active customer — status check
        status = _to_str(raw.get("Account_Status__c")) or ""
        is_active = "customer" in status.lower() or "renewal" in status.lower() or status in CUSTOMER_STAGES

        health_status = _to_str(raw.get("Health_Status__c"))

        # Open expansion opp — any open opp on this account
        has_open_opp = any(
            _to_str(o.get("stage")) in OPEN_OPP_STAGES for o in opps
        )

        # Usage rollups from raw SF data (custom fields)
        usage = UsageCounts(
            field_events_all_time=_to_float(raw.get("Number_of_Field_Events__c")),
            third_party_events_all_time=_to_float(raw.get("No_of_3rd_party_events_year__c")),
            webinars_all_time=_to_float(raw.get("Number_of_Webinars__c")),
            standard_in_person=0.0,
            standard_hybrid=0.0,
            standard_virtual=0.0,
            conferences_all_time=0.0,
        )

        # 3P signals from SF custom fields
        s3p = Signals3P(
            event_role_hiring_90d=None,
            competitor_mentions_g2_90d=_to_int(raw.get("G2_Total_Pageviews__c")),
            competitor_in_stack=_split_raw(raw.get("Competitor_Stack__c")),
        )

        # 1P signals from Factors.ai custom fields
        s1p = Signals1P(
            factors_intent_label=_to_str(raw.get("Factors_Engagement_Level__c")),
            demo_pricing_visits_90d=None,
            factors_last_intent_date=_to_str(raw.get("Factors_last_intent_date__c")),
        )

        # ICP population from SF
        icp = IcpPopulation()

        # Conversations from Gong + Fireflies
        conversations = self._build_conversations(gong_calls, fireflies_meetings, account_name, aid15)

        # Contacts from SF
        sf_contacts = [self._build_sf_contact(c) for c in contacts]
        if not sf_contacts:
            self.dq_log.add("contacts_sf_no_match", f"sf_id={sf_id}", account_id=aid15, account_name=account_name)

        # Account profile
        segment = _to_str(raw.get("Account_Segment__c"))
        acv = _to_float(raw.get("Total_Contract_Value_TCV__c")) or _to_float(raw.get("Current_contract_value__c")) or None

        return AccountNode(
            account_id_18=aid18,
            account_id_15=aid15,
            account_name=account_name,
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
            icp_population=icp,
            conversations=conversations,
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

        # Gong — use the most recent call's summary as the primary summary
        gong_summary = None
        gong_key_points: list[str] = []
        gong_competitors: list[str] = []
        gong_products: list[str] = []
        date_range: Optional[str] = None

        if gong_calls:
            latest = gong_calls[0]  # already sorted desc
            gong_summary = _to_str(latest.get("summary"))
            gong_key_points = _listify(latest.get("key_points"))
            gong_competitors = _listify(latest.get("topics"))
            if gong_calls[-1].get("date") and gong_calls[0].get("date"):
                date_range = f"{gong_calls[-1]['date'][:10]} → {gong_calls[0]['date'][:10]}"

        # Fireflies — latest meeting summary + action items
        ff_overview = None
        ff_action_items: list[str] = []
        ff_topics: list[str] = []

        if fireflies:
            latest_ff = fireflies[0]
            ff_overview = _to_str(latest_ff.get("summary"))
            ff_action_items = _listify(latest_ff.get("action_items"))
            ff_topics = _listify(latest_ff.get("key_questions"))

        return Conversations(
            has_gong=len(gong_calls) > 0,
            has_fireflies=len(fireflies) > 0,
            total_calls=len(gong_calls) + len(fireflies),
            date_range=date_range,
            gong_business_summary=gong_summary,
            gong_product_interests=gong_products,
            gong_competitors_mentioned=gong_competitors,
            gong_key_points=gong_key_points,
            fireflies_overview=ff_overview,
            fireflies_action_items=ff_action_items,
            fireflies_topics=ff_topics,
        )

    def _build_sf_contact(self, c: dict) -> Contact:
        first = _to_str(c.get("first_name")) or ""
        last = _to_str(c.get("last_name")) or ""
        name = (first + " " + last).strip() or "(unknown)"
        raw = c.get("raw") or {}
        return Contact(
            name=name,
            title=_to_str(c.get("title")),
            email=_to_str(c.get("email")),
            linkedin=_to_str(raw.get("LinkedIn_URL__c")),
            seniority=None,
            persona=None,
            persona_fit_score=None,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _listify(value: Any) -> list[str]:
    """Coerce a DB value (list, string, None) to list[str]."""
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
