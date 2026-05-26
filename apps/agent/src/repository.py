"""Repository — loads the xlsx once, builds AccountNodes joined across all sheets.

Authoritative rules (build spec §2, §3, §15):
- AE name:  Account-Data!C  (col 3,  "Account Owner")
- AE role:  Account-Data!AL (col 38, "Owner Role")
- CSM name: Account-Data!DV (col 126, "CSM owner")
- `Expansion Data!D` is unreliable — overridden from Account-Data on every join.
- Account IDs: Expansion Data has 18-char IDs; Account-Data has 15-char. Truncate to 15 to join.
- Gong+Fireflies joined by Account ID (also 18-char in source).
- Contact sheets joined by Account Name (normalized).
- All join misses → run_log/data_quality.csv. Do not silently drop.
- Missing CSM → route to AE only, set `ownership.csm_missing=True`.

The LangGraph nodes never call into this module's internals — they receive a
list of AccountNode and operate on those. In V1.5 this file is the only place
that changes when we swap to Postgres.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_15(account_id: Any) -> Optional[str]:
    """Truncate an 18-char Salesforce ID to the 15-char case-sensitive form.

    Returns None for missing / unparseable inputs.
    """
    if account_id is None or pd.isna(account_id):
        return None
    s = str(account_id).strip()
    if not s:
        return None
    return s[:15]


def _norm_name(name: Any) -> str:
    if name is None or pd.isna(name):
        return ""
    return " ".join(str(name).strip().casefold().split())


def _to_date(value: Any) -> Optional[date]:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.to_datetime(value).date()
    except (ValueError, TypeError):
        return None


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _to_int(value: Any) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _to_str(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def _bool_from_flag(value: Any) -> bool:
    """Coerce numeric/text flag columns to bool. >0 or 'yes'/'true' → True."""
    if value is None or pd.isna(value):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    s = str(value).strip().casefold()
    return s in {"1", "true", "yes", "y"}


def _split_list(value: Any, sep: str = ";") -> list[str]:
    s = _to_str(value)
    if not s:
        return []
    # Tolerate semicolon, pipe, or comma separators.
    parts: list[str] = []
    for chunk in s.replace("|", sep).split(sep):
        for piece in chunk.split(","):
            p = piece.strip()
            if p:
                parts.append(p)
    return parts


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
    """Accumulates DQ findings and flushes to run_log/data_quality.csv."""

    def __init__(self) -> None:
        self._issues: list[DataQualityIssue] = []

    def add(
        self,
        issue: str,
        detail: str = "",
        account_id: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> None:
        self._issues.append(
            DataQualityIssue(
                account_id=account_id, account_name=account_name, issue=issue, detail=detail
            )
        )

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


# Column name constants (must match the xlsx headers exactly; verified Phase 2).
_AD_AE = "Account Owner"  # col 3
_AD_OWNER_ROLE = "Owner Role"  # col 38
_AD_CSM = "CSM owner"  # col 126
_AD_ACCOUNT_ID = "Account ID"  # col 10
_AD_LAST_ACTIVITY = "Last Activity"  # col 33
_AD_HAS_OPEN_OPP = "Has Open Expansion Opp?"  # col 196
_AD_HEALTH_STATUS = "Health Status"  # col 198
_AD_INACTIVE_90 = "Inactive > 90 days?"  # col 205
_AD_IS_ACTIVE = "Is Active Customer"  # col 207
_AD_LATEST_EXP_END = "Latest Expansion Contract End"  # col 218
_AD_PLAN_END = "Plan End Date"  # col 255


@dataclass
class LoadedSheets:
    """Raw frames after read. Carried around to keep things explicit."""

    expansion: pd.DataFrame
    account_data: pd.DataFrame
    gong: pd.DataFrame
    contacts_sf: pd.DataFrame
    contacts_clay: pd.DataFrame


class Repository:
    """Builds in-memory AccountNodes from the xlsx.

    Lifecycle:
        repo = Repository(path)
        nodes = repo.load_accounts()      # builds 117 AccountNodes
        repo.dq_log.write_csv(...)        # persist DQ findings
    """

    def __init__(self, xlsx_path: Path) -> None:
        self.xlsx_path = Path(xlsx_path)
        self.dq_log = DataQualityLog()
        self._loaded: Optional[LoadedSheets] = None

    # ---- public API ----------------------------------------------------

    def load_accounts(self) -> list[AccountNode]:
        sheets = self._load_sheets()
        ad_by_id = self._index_account_data(sheets.account_data)
        gong_by_id = self._index_gong(sheets.gong)
        sf_by_name = self._index_contacts_sf(sheets.contacts_sf)
        clay_by_name = self._index_contacts_clay(sheets.contacts_clay)

        nodes: list[AccountNode] = []
        for _, row in sheets.expansion.iterrows():
            node = self._build_node(row, ad_by_id, gong_by_id, sf_by_name, clay_by_name)
            if node is not None:
                nodes.append(node)
        return nodes

    # ---- sheet IO ------------------------------------------------------

    def _load_sheets(self) -> LoadedSheets:
        if self._loaded is not None:
            return self._loaded
        if not self.xlsx_path.exists():
            raise FileNotFoundError(f"xlsx not found at {self.xlsx_path}")
        # Expansion Data has its header on row 2 (row 1 is blank).
        expansion = pd.read_excel(self.xlsx_path, sheet_name="Expansion Data", header=1)
        account_data = pd.read_excel(self.xlsx_path, sheet_name="Account-Data", header=0)
        gong = pd.read_excel(self.xlsx_path, sheet_name="Gong+Fireflies Transcripts", header=0)
        contacts_sf = pd.read_excel(self.xlsx_path, sheet_name="Contacts_From_SF", header=0)
        contacts_clay = pd.read_excel(self.xlsx_path, sheet_name="Contacts Not in ProdSF", header=0)
        self._loaded = LoadedSheets(
            expansion=expansion,
            account_data=account_data,
            gong=gong,
            contacts_sf=contacts_sf,
            contacts_clay=contacts_clay,
        )
        return self._loaded

    # ---- indexing ------------------------------------------------------

    def _index_account_data(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        out: dict[str, pd.Series] = {}
        for _, row in df.iterrows():
            aid15 = _to_15(row.get(_AD_ACCOUNT_ID))
            if not aid15:
                self.dq_log.add(
                    "missing_account_id_in_account_data",
                    detail=f"Account Name={row.get('Account Name')!r}",
                    account_name=_to_str(row.get("Account Name")),
                )
                continue
            if aid15 in out:
                self.dq_log.add(
                    "duplicate_account_id_in_account_data",
                    detail=f"id={aid15}",
                    account_id=aid15,
                    account_name=_to_str(row.get("Account Name")),
                )
            out[aid15] = row
        return out

    def _index_gong(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        out: dict[str, pd.Series] = {}
        for _, row in df.iterrows():
            aid15 = _to_15(row.get("Account ID"))
            if not aid15:
                continue
            out[aid15] = row
        return out

    def _index_contacts_sf(self, df: pd.DataFrame) -> dict[str, list[pd.Series]]:
        out: dict[str, list[pd.Series]] = {}
        for _, row in df.iterrows():
            name = _norm_name(row.get("Account Name"))
            if not name:
                continue
            out.setdefault(name, []).append(row)
        return out

    def _index_contacts_clay(self, df: pd.DataFrame) -> dict[str, list[pd.Series]]:
        out: dict[str, list[pd.Series]] = {}
        for _, row in df.iterrows():
            name = _norm_name(row.get("Account Name"))
            if not name:
                continue
            out.setdefault(name, []).append(row)
        return out

    # ---- node builder --------------------------------------------------

    def _build_node(
        self,
        row: pd.Series,
        ad_by_id: dict[str, pd.Series],
        gong_by_id: dict[str, pd.Series],
        sf_by_name: dict[str, list[pd.Series]],
        clay_by_name: dict[str, list[pd.Series]],
    ) -> Optional[AccountNode]:
        aid18 = _to_str(row.get("18-digit Account Id"))
        if not aid18:
            self.dq_log.add(
                "missing_account_id_in_expansion_data",
                detail=f"Account Name={row.get('Account Name')!r}",
                account_name=_to_str(row.get("Account Name")),
            )
            return None
        aid15 = _to_15(aid18)
        if not aid15:
            return None

        account_name = _to_str(row.get("Account Name")) or "(unknown)"
        flags: list[str] = []

        # Ownership — authoritative source = Account-Data
        ad_row = ad_by_id.get(aid15)
        if ad_row is None:
            self.dq_log.add(
                "expansion_account_not_in_account_data",
                detail=f"id15={aid15}",
                account_id=aid15,
                account_name=account_name,
            )
            flags.append("account_data_missing")
            ownership = Ownership(csm_missing=True)
        else:
            ae_name = _to_str(ad_row.get(_AD_AE))
            ae_role = _to_str(ad_row.get(_AD_OWNER_ROLE))
            csm_name = _to_str(ad_row.get(_AD_CSM))
            ownership = Ownership(
                ae_name=ae_name,
                ae_role=ae_role,
                csm_name=csm_name,
                csm_missing=csm_name is None,
            )
            if csm_name is None:
                self.dq_log.add(
                    "missing_csm",
                    detail="routing to AE only",
                    account_id=aid15,
                    account_name=account_name,
                )
                flags.append("missing_csm")
            # Note that Expansion Data!D is overridden — keep the override audited.
            expansion_d = _to_str(row.get("Account Owner"))
            if expansion_d and ae_name and expansion_d != ae_name:
                self.dq_log.add(
                    "expansion_owner_d_differs_from_account_data_c",
                    detail=f"expansion_d={expansion_d!r} account_data_c={ae_name!r}",
                    account_id=aid15,
                    account_name=account_name,
                )

        # Current state
        adoption_health = _to_str(row.get("Adoption Health from Prod"))
        gap = _to_str(row.get("Use case gap \n(Prod data and usecase 2025)"))
        last_activity_date = _to_date(ad_row.get(_AD_LAST_ACTIVITY)) if ad_row is not None else None
        plan_end = _to_date(ad_row.get(_AD_PLAN_END)) if ad_row is not None else None
        latest_exp_end = (
            _to_date(ad_row.get(_AD_LATEST_EXP_END)) if ad_row is not None else None
        )
        has_open = _bool_from_flag(ad_row.get(_AD_HAS_OPEN_OPP)) if ad_row is not None else False
        inactive_over_90 = (
            _bool_from_flag(ad_row.get(_AD_INACTIVE_90)) if ad_row is not None else False
        )
        # Is Active Customer comes through as 1.0/0.0; default True if missing.
        if ad_row is not None and not pd.isna(ad_row.get(_AD_IS_ACTIVE)):
            is_active = _bool_from_flag(ad_row.get(_AD_IS_ACTIVE))
        else:
            is_active = True
        health_status = _to_str(ad_row.get(_AD_HEALTH_STATUS)) if ad_row is not None else None

        # Usage rollups (Expansion Data L–R + AD–AG region)
        usage = UsageCounts(
            field_events_all_time=_to_float(row.get("field_all_time")),
            third_party_events_all_time=_to_float(row.get("third_party_all_time")),
            webinars_all_time=_to_float(row.get("webinar_all_time")),
            standard_in_person=_to_float(row.get("Standard_in-person")),
            standard_hybrid=_to_float(row.get("Standard_hybrid")),
            standard_virtual=_to_float(row.get("Standard_virtual")),
            # Conferences are tracked separately; no _all_time column in V1, leave 0.
            conferences_all_time=0.0,
        )

        # 3P signal: hiring counts (Expansion Data AA-AC)
        s3p = Signals3P(
            event_role_hiring_90d=_sum_int(
                row.get("Conferences Hiring Count"),
                row.get("Webinars Hiring"),
                row.get("Field Events Hiring Count"),
            ),
        )

        # ICP supply (W–Z)
        icp = IcpPopulation(
            conferences_icp_count=_to_int(row.get("Count_Conferences ICPs")) or 0,
            field_events_icp_count=_to_int(row.get("Count_Field Events ICPs")) or 0,
            webinar_icp_count=_to_int(row.get("Count_Webinar ICPs")) or 0,
            third_party_icp_count=_to_int(row.get("Count_3PE ICPs")) or 0,
        )

        # Conversations (Gong+Fireflies)
        gong_row = gong_by_id.get(aid15)
        if gong_row is None:
            self.dq_log.add(
                "gong_fireflies_no_match",
                detail=f"id15={aid15}",
                account_id=aid15,
                account_name=account_name,
            )
            conversations = Conversations()
        else:
            conversations = Conversations(
                has_gong=_to_str(gong_row.get("Has Gong Data")) in {"Yes", "yes", "True", "true"},
                has_fireflies=_to_str(gong_row.get("Has Fireflies Data"))
                in {"Yes", "yes", "True", "true"},
                total_calls=_to_int(gong_row.get("Total Calls")) or 0,
                date_range=_to_str(gong_row.get("Gong - Date Range"))
                or _to_str(gong_row.get("Fireflies - Date Range")),
                gong_business_summary=_to_str(gong_row.get("Gong - Business Summary")),
                gong_product_interests=_split_list(gong_row.get("Gong - Product Interests")),
                gong_competitors_mentioned=_split_list(
                    gong_row.get("Gong - Competitors Mentioned")
                ),
                gong_key_points=_split_list(gong_row.get("Gong - Key Points")),
                fireflies_overview=_to_str(gong_row.get("Fireflies - Overview Summary")),
                fireflies_action_items=_split_list(gong_row.get("Fireflies - Action Items")),
                fireflies_topics=_split_list(gong_row.get("Fireflies - Topics Discussed")),
            )

        # Contacts
        name_key = _norm_name(account_name)
        sf_rows = sf_by_name.get(name_key, [])
        clay_rows = clay_by_name.get(name_key, [])
        if not sf_rows:
            self.dq_log.add(
                "contacts_sf_no_match",
                detail=f"name_key={name_key}",
                account_id=aid15,
                account_name=account_name,
            )
        if not clay_rows:
            self.dq_log.add(
                "contacts_clay_no_match",
                detail=f"name_key={name_key}",
                account_id=aid15,
                account_name=account_name,
            )

        contacts_sf = [_build_sf_contact(r) for r in sf_rows]
        contacts_clay = [_build_clay_contact(r) for r in clay_rows]

        # Account profile
        segment = _to_str(row.get("Account Segment"))
        acv = _to_float(row.get("ACV"), default=0.0) or None
        target_departments = _split_list(row.get("Target Departments"))
        sales_model = _to_str(row.get("Sales Model"))
        target_customers = _split_list(row.get("Target Customers"))

        return AccountNode(
            account_id_18=aid18,
            account_id_15=aid15,
            account_name=account_name,
            domain=_to_str(row.get("Account Domain")),
            ownership=ownership,
            segment=segment,
            acv_usd=acv,
            target_departments=target_departments,
            sales_model=sales_model,
            target_customers=target_customers,
            use_case_gap_field=gap,
            adoption_health=adoption_health,
            last_activity_date=last_activity_date,
            plan_end_date=plan_end,
            latest_expansion_contract_end=latest_exp_end,
            has_open_expansion_opp=has_open,
            is_active_customer=is_active,
            inactive_over_90_days=inactive_over_90,
            health_status=health_status,
            usage=usage,
            signals_1p=Signals1P(),  # not in static dataset; placeholder
            signals_2p=Signals2P(),
            signals_3p=s3p,
            icp_population=icp,
            conversations=conversations,
            contacts_in_product_sf=contacts_sf,
            contacts_not_in_product_clay=contacts_clay,
            data_quality_flags=flags,
        )


# ---------------------------------------------------------------------------
# Module-level helpers (kept out of the class so they're easy to unit-test)
# ---------------------------------------------------------------------------


def _sum_int(*values: Any) -> Optional[int]:
    total = 0
    saw_any = False
    for v in values:
        i = _to_int(v)
        if i is not None:
            total += i
            saw_any = True
    return total if saw_any else None


def _build_sf_contact(row: pd.Series) -> Contact:
    first = _to_str(row.get("First Name")) or ""
    last = _to_str(row.get("Last Name")) or ""
    name = (first + " " + last).strip() or "(unknown)"
    return Contact(
        name=name,
        title=_to_str(row.get("Title")),
        seniority=_to_str(row.get("Seniority")),
        persona=_to_str(row.get("Persona")),
        persona_fit_score=_to_float(row.get("Persona Fit Score"), default=0.0) or None,
        linkedin=_to_str(row.get("LinkedIn URL")),
        email=_to_str(row.get("Email")),
    )


def _build_clay_contact(row: pd.Series) -> ClayContact:
    # Tagged use-case is whichever per-event column is non-zero.
    tagged: Optional[str] = None
    for col, label in (
        ("Conferences", "Conferences"),
        ("Webinar", "Webinar"),
        ("Field Events", "Field Events"),
        ("Third-Party Events", "Third-Party Events"),
    ):
        v = _to_int(row.get(col))
        if v and v > 0:
            tagged = label
            break
    return ClayContact(
        name=_to_str(row.get("Contact Name")) or "(unknown)",
        title=_to_str(row.get("Title")),
        linkedin=_to_str(row.get("LinkedIn URL")),
        email=_to_str(row.get("Consolidated Email (Clay + Prod)")),
        tagged_use_case=tagged,
        found_in_prod=_bool_from_flag(row.get("Found in Prod?")),
    )
