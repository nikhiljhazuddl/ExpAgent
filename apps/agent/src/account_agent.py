"""AccountAgent — the per-account intelligent object.

This is the architectural move from "signal-based workflow" to "account-as-agent".
Every account is an independent object with four memory layers:

  1. Present State Memory — current snapshot (the AccountNode)
  2. Historical Memory    — temporal snapshots across runs
  3. Narrative Memory     — the evolving story of this account
  4. Feedback Memory      — AI recommendations + human actions + outcomes

V1 scope:
- Present State: fully implemented (AccountNode).
- Historical Memory: V1 reads previous runs from run_log/ — bootstrap; full
  time-series lands in V1.5 with Postgres.
- Narrative Memory: V1 lite — composes from Gong/Fireflies summaries + the
  last 3 signal narratives + the last 3 feedback entries. Full accumulation in V1.5.
- Feedback Memory: reads run_log/outcomes.csv keyed by account_id; the
  orchestrator passes feedback into the next reasoning call.

The orchestrator queries AccountAgents rather than raw sheets / queues.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from schemas.account_node import AccountNode
from schemas.signal import Signal


@dataclass
class HistoricalSnapshot:
    """A single point-in-time snapshot of an account."""

    run_id: str
    captured_at: datetime
    adoption_health: Optional[str]
    last_activity_days_ago: Optional[int]
    renewal_proximity_days: Optional[int]
    usage_total: float
    is_active_customer: bool
    has_open_expansion_opp: bool
    priority_score: Optional[float] = None
    final_score: Optional[float] = None
    priority_band: Optional[str] = None
    is_signal: Optional[bool] = None
    missing_use_case: Optional[str] = None


@dataclass
class FeedbackEntry:
    """One human response to an AI recommendation."""

    timestamp: str
    run_id: str
    signal_id: str
    user: str
    role: str
    relevant: Optional[bool] = None
    actioned: Optional[bool] = None
    notes: str = ""


@dataclass
class NarrativeChunk:
    """One paragraph in the evolving account story."""

    captured_at: datetime
    source: str  # "gong" | "fireflies" | "agent_signal" | "feedback" | "csm_note"
    text: str


@dataclass
class AccountAgent:
    """The per-account agent. Wraps an AccountNode and exposes the four memory layers."""

    node: AccountNode

    # The four memory layers
    history: list[HistoricalSnapshot] = field(default_factory=list)
    narrative: list[NarrativeChunk] = field(default_factory=list)
    feedback: list[FeedbackEntry] = field(default_factory=list)

    # --- Present State Memory ---------------------------------------------

    @property
    def account_id(self) -> str:
        return self.node.account_id_15

    @property
    def account_name(self) -> str:
        return self.node.account_name

    def present_state_summary(self) -> dict:
        """Snapshot for the orchestrator — the 'current memory'."""
        return {
            "account_id": self.node.account_id_15,
            "account_name": self.node.account_name,
            "ae": self.node.ownership.ae_name,
            "csm": self.node.ownership.csm_name,
            "adoption_health": self.node.adoption_health,
            "is_active_customer": self.node.is_active_customer,
            "has_open_expansion_opp": self.node.has_open_expansion_opp,
            "use_case_gap_field": self.node.use_case_gap_field,
            "usage_total": self.node.usage.total,
            "last_activity_date": (
                self.node.last_activity_date.isoformat() if self.node.last_activity_date else None
            ),
            "plan_end_date": (
                self.node.plan_end_date.isoformat() if self.node.plan_end_date else None
            ),
            "sf_contact_count": len(self.node.contacts_in_product_sf),
            "clay_contact_count": len(self.node.contacts_not_in_product_clay),
        }

    # --- Historical Memory ------------------------------------------------

    def add_snapshot(self, snap: HistoricalSnapshot) -> None:
        self.history.append(snap)
        self.history.sort(key=lambda s: s.captured_at)

    def historical_summary(self, *, max_points: int = 6) -> list[dict]:
        """The last N snapshots, oldest → newest, for trend analysis."""
        recent = self.history[-max_points:]
        return [
            {
                "run_id": s.run_id,
                "captured_at": s.captured_at.isoformat(),
                "adoption_health": s.adoption_health,
                "usage_total": s.usage_total,
                "priority_band": s.priority_band,
                "final_score": s.final_score,
                "is_signal": s.is_signal,
                "missing_use_case": s.missing_use_case,
            }
            for s in recent
        ]

    def has_trend(self) -> bool:
        """Do we have enough history to compute a trend?"""
        return len(self.history) >= 2

    # --- Narrative Memory --------------------------------------------------

    def add_narrative(self, chunk: NarrativeChunk) -> None:
        self.narrative.append(chunk)
        self.narrative.sort(key=lambda c: c.captured_at)

    def bootstrap_narrative(self) -> None:
        """Seed narrative from Gong + Fireflies summaries on the node."""
        now = datetime.utcnow()
        if self.node.conversations.gong_business_summary:
            self.add_narrative(
                NarrativeChunk(
                    captured_at=now,
                    source="gong",
                    text=self.node.conversations.gong_business_summary,
                )
            )
        if self.node.conversations.fireflies_overview:
            self.add_narrative(
                NarrativeChunk(
                    captured_at=now,
                    source="fireflies",
                    text=self.node.conversations.fireflies_overview,
                )
            )

    def narrative_summary(self, *, max_chunks: int = 8) -> list[dict]:
        """Latest narrative chunks for the reasoning agent."""
        recent = self.narrative[-max_chunks:]
        return [
            {
                "captured_at": c.captured_at.isoformat(),
                "source": c.source,
                "text": c.text,
            }
            for c in recent
        ]

    # --- Feedback Memory ---------------------------------------------------

    def add_feedback(self, fb: FeedbackEntry) -> None:
        self.feedback.append(fb)

    def feedback_summary(self) -> dict:
        """What humans have said about this account's past recommendations."""
        if not self.feedback:
            return {"count": 0, "marked_relevant": 0, "marked_actioned": 0, "notes": []}
        return {
            "count": len(self.feedback),
            "marked_relevant": sum(1 for f in self.feedback if f.relevant is True),
            "marked_not_relevant": sum(1 for f in self.feedback if f.relevant is False),
            "marked_actioned": sum(1 for f in self.feedback if f.actioned is True),
            "notes": [f.notes for f in self.feedback if f.notes][-5:],
        }


# ---------------------------------------------------------------------------
# Builders — populate AccountAgents from disk + previous runs
# ---------------------------------------------------------------------------


def hydrate_agents_from_history(
    agents: dict[str, AccountAgent], run_log_dir: Path
) -> None:
    """Read run_log/agent_runs.csv + signals.csv to backfill historical snapshots.

    This is the V1 implementation of Historical Memory. V1.5 swaps this for a
    Postgres query against an `account_snapshots` table.
    """
    signals_csv = run_log_dir / "signals.csv"
    if not signals_csv.exists():
        return

    with signals_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            account_id = row.get("account_id")
            if not account_id or account_id not in agents:
                continue
            try:
                payload = json.loads(row.get("payload_json", "{}"))
            except json.JSONDecodeError:
                continue
            agent = agents[account_id]
            snap = HistoricalSnapshot(
                run_id=row.get("run_id", "?"),
                captured_at=datetime.utcnow(),  # CSV doesn't have a timestamp col; fine for V1
                adoption_health=agent.node.adoption_health,
                last_activity_days_ago=None,
                renewal_proximity_days=None,
                usage_total=agent.node.usage.total,
                is_active_customer=agent.node.is_active_customer,
                has_open_expansion_opp=agent.node.has_open_expansion_opp,
                priority_score=payload.get("priority_score"),
                final_score=payload.get("final_score"),
                priority_band=payload.get("priority_band"),
                is_signal=payload.get("is_signal"),
                missing_use_case=payload.get("missing_use_case"),
            )
            agent.add_snapshot(snap)


def hydrate_agents_with_feedback(
    agents: dict[str, AccountAgent], run_log_dir: Path
) -> None:
    """Read run_log/outcomes.csv to backfill Feedback Memory."""
    outcomes_csv = run_log_dir / "outcomes.csv"
    if not outcomes_csv.exists():
        return
    with outcomes_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            signal_id = row.get("signal_id", "")
            # signal_id format: "<run_id>:<account_id_15>"
            account_id = signal_id.split(":")[-1] if ":" in signal_id else ""
            if account_id not in agents:
                continue
            agents[account_id].add_feedback(
                FeedbackEntry(
                    timestamp=row.get("timestamp", ""),
                    run_id=row.get("run_id", ""),
                    signal_id=signal_id,
                    user=row.get("user", ""),
                    role=row.get("role", ""),
                    relevant=_csv_bool(row.get("relevant")),
                    actioned=_csv_bool(row.get("actioned")),
                    notes=row.get("notes", ""),
                )
            )


def _csv_bool(value: Optional[str]) -> Optional[bool]:
    if not value:
        return None
    v = value.strip().casefold()
    if v == "true":
        return True
    if v == "false":
        return False
    return None


def build_agents(
    nodes: list[AccountNode], run_log_dir: Path
) -> dict[str, AccountAgent]:
    """Build AccountAgents for every node and hydrate the memory layers."""
    agents: dict[str, AccountAgent] = {}
    for node in nodes:
        agent = AccountAgent(node=node)
        agent.bootstrap_narrative()
        agents[agent.account_id] = agent

    hydrate_agents_from_history(agents, run_log_dir)
    hydrate_agents_with_feedback(agents, run_log_dir)
    return agents
