"""Build the LangGraph StateGraph.

Topology:
    START
      → load_accounts
      → filter_node          (and in parallel: notify_disqualified)
      → rank_node
      → assemble_node
      → (conditional: dry_run? → END ; else → reasoning fan-out)
      → score_one (parallel via Send)
      → cap_node
      → persist_node
      → END
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .nodes import (
    assemble_node,
    cap_node,
    fan_out_to_reasoning,
    filter_node,
    load_accounts_node,
    notify_disqualified_node,
    persist_node,
    rank_node,
    score_one_node,
)
from .state import AgentState


def _after_assemble(state: AgentState) -> str:
    """Conditional: dry-run skips LLM and goes straight to persist."""
    cfg = state["config"]
    return "persist" if cfg.dry_run else "fan_out"


def build_graph(*, checkpointer=None):
    """Compile and return the StateGraph.

    ``checkpointer`` defaults to MemorySaver for V1. In V1.5 we'll inject a
    PostgresSaver — that's the only line that needs to change to swap state stores.
    """
    g = StateGraph(AgentState)

    g.add_node("load_accounts", load_accounts_node)
    g.add_node("filter", filter_node)
    g.add_node("notify_disqualified", notify_disqualified_node)
    g.add_node("rank", rank_node)
    g.add_node("assemble", assemble_node)
    g.add_node("score_one", score_one_node)
    g.add_node("cap", cap_node)
    g.add_node("persist", persist_node)

    g.add_edge(START, "load_accounts")
    g.add_edge("load_accounts", "filter")

    # filter fans out to both notify (no-op pass-through) and rank.
    g.add_edge("filter", "notify_disqualified")
    g.add_edge("filter", "rank")
    g.add_edge("notify_disqualified", "assemble")  # joins
    g.add_edge("rank", "assemble")  # joins

    # Conditional: dry-run skips reasoning.
    g.add_conditional_edges(
        "assemble",
        _after_assemble,
        {"fan_out": "fan_out_router", "persist": "persist"},
    )

    # Fan-out router is a virtual node — implemented as a conditional-edges fn.
    g.add_node("fan_out_router", lambda s: {})
    g.add_conditional_edges("fan_out_router", fan_out_to_reasoning, ["score_one"])

    g.add_edge("score_one", "cap")
    g.add_edge("cap", "persist")
    g.add_edge("persist", END)

    if checkpointer is None:
        checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)
