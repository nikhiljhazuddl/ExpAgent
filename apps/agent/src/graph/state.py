"""AgentState — the shared TypedDict that flows through every LangGraph node."""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Optional, TypedDict

from schemas.account_context import AccountContext
from schemas.account_node import AccountNode
from schemas.notification import Notification
from schemas.signal import Signal


@dataclass
class RunConfig:
    run_id: str
    today: date
    dry_run: bool = False
    max_concurrency: int = 8
    limit: Optional[int] = None  # cap number of LLM calls (debug)
    model: Optional[str] = None
    per_role_cap: int = 5  # top N per AE / per CSM


@dataclass
class RunMetrics:
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    failed_validations: int = 0
    duration_ms: int = 0


@dataclass
class RankedCandidatePayload:
    """Lightweight projection used by the graph (avoids carrying full AccountNode in state)."""

    account_id_15: str
    account_name: str
    priority_score: float
    ae_name: Optional[str]
    csm_name: Optional[str]


class AgentState(TypedDict, total=False):
    run_id: str
    triggered_at: datetime
    config: RunConfig

    all_accounts: list[AccountNode]
    triggered: list[AccountNode]
    disqualified: list[Notification]
    survivors: list[AccountNode]
    ranked: list[RankedCandidatePayload]

    contexts: dict[str, AccountContext]
    signals: Annotated[list[Signal], operator.add]  # accumulator via Send fan-out

    capped_by_ae: dict[str, list[Signal]]
    capped_by_csm: dict[str, list[Signal]]
    extras_by_ae: dict[str, list[Signal]]    # ranks 6..10 per AE
    extras_by_csm: dict[str, list[Signal]]   # ranks 6..10 per CSM

    metrics: RunMetrics
