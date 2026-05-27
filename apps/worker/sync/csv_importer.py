"""Import 594 accounts + people from the Expansion Agent CSV into Supabase.

Run once:  uv run python -m sync.csv_importer
"""

from __future__ import annotations

import csv
import logging
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

from sync.account_resolver import AccountResolver, normalise_domain

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
log = logging.getLogger("csv_importer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
ACCOUNT_CSV = DATA_DIR / "Expansion_Agent__Account-Data.csv"


def _parse_date(v: str) -> str | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(v.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", "").replace("$", "").strip())
    except (ValueError, AttributeError):
        return None


def run() -> None:
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    resolver = AccountResolver(sb)

    with ACCOUNT_CSV.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    log.info("importing %d accounts from CSV…", len(rows))

    accounts_upserted = 0
    for row in rows:
        name = (row.get("Account Name") or "").strip()
        if not name:
            continue

        website = row.get("Website") or row.get("Domain Name") or ""
        domain = normalise_domain(website)
        sf_id = row.get("18-digit Account Id") or row.get("Account ID") or None
        if sf_id:
            sf_id = sf_id.strip() or None

        extra = {
            "industry":   row.get("Industry"),
            "segment":    row.get("Account Segment") or row.get("Segment"),
            "owner_name": row.get("Account Owner"),
            "csm_name":   row.get("CSM owner"),
            "health_status": row.get("Health Status"),
            "acv":        _num(row.get("ACV_acc", "")),
            "churn_risk": row.get("Churn Risk Category"),
            "expansion_candidate": (row.get("Expansion Candidate?") or "").strip().lower() == "yes",
        }
        # contract dates
        start_raw = row.get("Contract_start_date_latest_opp", "")
        end_raw = row.get("Plan End Date") or row.get("Incumbent Contract End (Sales)", "")
        if start_raw:
            extra["contract_start"] = _parse_date(start_raw)
        if end_raw:
            extra["contract_end"] = _parse_date(end_raw)

        # remove None-valued extras to avoid overwriting good data
        extra = {k: v for k, v in extra.items() if v not in (None, "", [])}

        uid = resolver.resolve(
            name=name,
            domain=domain,
            sf_id=sf_id,
            extra_fields=extra,
        )

        # upsert into sf_accounts raw table too
        if sf_id:
            sb.table("sf_accounts").upsert({
                "sf_id": sf_id,
                "account_id": uid,
                "name": name,
                "industry": row.get("Industry"),
                "owner_name": row.get("Account Owner"),
                "csm_name": row.get("CSM owner"),
                "health_score": row.get("Health Status"),
                "raw": {"segment": row.get("Account Segment"), "acv": row.get("ACV_acc")},
                "synced_at": datetime.utcnow().isoformat(),
            }, on_conflict="sf_id").execute()

        accounts_upserted += 1

    log.info("done — %d accounts upserted", accounts_upserted)


if __name__ == "__main__":
    run()
