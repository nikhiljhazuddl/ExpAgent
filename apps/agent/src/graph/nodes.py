"""LangGraph node functions.

Each node is a pure function over AgentState. Nodes never touch the filesystem
directly — they delegate to repository / persist. This is what makes the
V1 → V1.5 swap painless: the same graph runs against Postgres.
"""

from __future__ import annotations

import logging
from datetime import datetime

from langgraph.types import Send

from config.settings import get_settings
from schemas.signal import Signal, SignalOwner, SignalOwnership
from src.context_builder import build_context
from src.filter_logic import run_filter
from src.rank_logic import rank_survivors
from src.repository import Repository

from .state import AgentState, RankedCandidatePayload, RunMetrics

logger = logging.getLogger(__name__)


# ---- node: load_accounts --------------------------------------------------


def load_accounts_node(state: AgentState) -> dict:
    settings = get_settings()
    repo = Repository(settings.data_xlsx_path)
    accounts = repo.load_accounts()
    # Persist DQ findings as part of every run. The persist_node will also re-flush.
    dq_path = settings.run_log_dir / "data_quality.csv"
    repo.dq_log.write_csv(dq_path)
    return {
        "all_accounts": accounts,
        "triggered_at": datetime.utcnow(),
        "metrics": state.get("metrics") or RunMetrics(),
    }


# ---- node: filter ---------------------------------------------------------


def filter_node(state: AgentState) -> dict:
    cfg = state["config"]
    result = run_filter(state["all_accounts"], cfg.today)
    return {
        "triggered": result.triggered,
        "survivors": result.survivors,
        "disqualified": result.notifications,
    }


# ---- node: rank -----------------------------------------------------------


def rank_node(state: AgentState) -> dict:
    cfg = state["config"]
    ranked = rank_survivors(state["survivors"], cfg.today)
    payload: list[RankedCandidatePayload] = []
    for c in ranked:
        payload.append(
            RankedCandidatePayload(
                account_id_15=c.node.account_id_15,
                account_name=c.node.account_name,
                priority_score=c.priority_score,
                ae_name=c.node.ownership.ae_name,
                csm_name=c.node.ownership.csm_name,
            )
        )
    return {"ranked": payload}


# ---- node: notify_disqualified --------------------------------------------


def notify_disqualified_node(state: AgentState) -> dict:
    """No-op state mutation. Notifications are already populated by filter_node;
    this node exists so the graph's parallel branch is explicit + future-extensible
    (e.g., Slack push later)."""
    notifs = state.get("disqualified") or []
    logger.info("Emitted %d disqualification notifications.", len(notifs))
    return {}


# ---- node: assemble (contexts) --------------------------------------------


def assemble_node(state: AgentState) -> dict:
    cfg = state["config"]
    # Map id → AccountNode for fast lookup
    by_id = {n.account_id_15: n for n in state["survivors"]}
    contexts = {}
    for cand in state["ranked"]:
        node = by_id.get(cand.account_id_15)
        if node is None:
            continue
        ctx = build_context(node, cand.priority_score, cfg.today)
        contexts[node.account_id_15] = ctx
    return {"contexts": contexts}


# ---- node: reasoning (Send fan-out) ---------------------------------------
# The dispatch happens via a conditional-edges function returning Send objects.
# The per-account subgraph is `score_one_node` below.


def fan_out_to_reasoning(state: AgentState):
    """Return one Send per ranked candidate; LangGraph executes them with
    max_concurrency from the runtime config (set at compile time)."""
    cfg = state["config"]
    contexts = state.get("contexts") or {}
    ranked = state.get("ranked") or []
    if cfg.limit is not None:
        ranked = ranked[: cfg.limit]
    sends = []
    for cand in ranked:
        ctx = contexts.get(cand.account_id_15)
        if ctx is None:
            continue
        sends.append(Send("score_one", {"context": ctx, "priority_score": cand.priority_score}))
    return sends


async def score_one_node(payload: dict) -> dict:
    """One Claude call per Send. Returns a dict that accumulates into `signals`."""
    from src.reasoning import score_account

    ctx = payload["context"]
    priority_score = payload["priority_score"]
    sig = await score_account(ctx)
    sig.priority_score = priority_score
    if sig.is_signal and sig.confidence is not None:
        sig.final_score = 0.5 * sig.confidence + 0.5 * priority_score
        # Apply spec's priority_band thresholds based on final_score.
        if sig.final_score >= 0.70:
            sig.priority_band = "high"
        elif sig.final_score >= 0.45:
            sig.priority_band = "medium"
        else:
            sig.priority_band = "low"
        # Stamp ownership from context (in case model omitted it).
        sig.ownership = sig.ownership or SignalOwnership(
            ae=SignalOwner(name=ctx.ownership.ae.name, role=ctx.ownership.ae.role),
            csm=SignalOwner(name=ctx.ownership.csm.name),
        )
    return {"signals": [sig]}


# ---- node: cap ------------------------------------------------------------


def cap_node(state: AgentState) -> dict:
    """Apply per-AE and per-CSM caps; drop low-band signals from delivery.

    Returns:
      - capped_by_ae / capped_by_csm: top-5 per role (the primary queue)
      - extras_by_ae / extras_by_csm: ranks 6-10 per role (the "show 5 more" reveal)
    """
    cfg = state["config"]
    cap = cfg.per_role_cap
    extras_cap = cap * 2  # ranks 6..10
    signals = state.get("signals") or []

    deliverable = [
        s for s in signals if s.is_signal and (s.priority_band or "low") != "low"
    ]
    deliverable.sort(key=lambda s: (s.final_score or 0.0), reverse=True)

    by_ae: dict[str, list[Signal]] = {}
    by_csm: dict[str, list[Signal]] = {}
    extras_ae: dict[str, list[Signal]] = {}
    extras_csm: dict[str, list[Signal]] = {}

    ae_seen: dict[str, int] = {}
    csm_seen: dict[str, int] = {}

    for s in deliverable:
        ae = (s.ownership.ae.name if s.ownership and s.ownership.ae else None) or "_unassigned_"
        csm = (s.ownership.csm.name if s.ownership and s.ownership.csm else None) or "_unassigned_"

        ae_idx = ae_seen.get(ae, 0)
        if ae_idx < cap:
            by_ae.setdefault(ae, []).append(s)
        elif ae_idx < extras_cap:
            extras_ae.setdefault(ae, []).append(s)
        ae_seen[ae] = ae_idx + 1

        if csm != "_unassigned_":
            csm_idx = csm_seen.get(csm, 0)
            if csm_idx < cap:
                by_csm.setdefault(csm, []).append(s)
            elif csm_idx < extras_cap:
                extras_csm.setdefault(csm, []).append(s)
            csm_seen[csm] = csm_idx + 1

    return {
        "capped_by_ae": by_ae,
        "capped_by_csm": by_csm,
        "extras_by_ae": extras_ae,
        "extras_by_csm": extras_csm,
    }


# ---- node: persist --------------------------------------------------------


def persist_node(state: AgentState) -> dict:
    from src.persist import persist_run

    persist_run(state)
    return {}
