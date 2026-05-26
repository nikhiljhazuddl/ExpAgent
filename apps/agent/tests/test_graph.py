"""End-to-end LangGraph integration test (dry-run path, no LLM)."""

from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path

import pytest

from src.graph.build import build_graph
from src.graph.state import RunConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "output"


def test_graph_compiles():
    graph = build_graph()
    assert graph is not None
    # the mermaid renderer is the cheapest non-IO check
    diagram = graph.get_graph().draw_mermaid()
    for node in ("load_accounts", "filter", "rank", "assemble", "score_one", "cap", "persist"):
        assert node in diagram


@pytest.mark.asyncio
async def test_dry_run_funnel_matches_spec():
    graph = build_graph()
    cfg = RunConfig(run_id="testrun-20260518", today=date(2026, 5, 18), dry_run=True)
    state = await graph.ainvoke(
        {"config": cfg}, config={"configurable": {"thread_id": "test-dry-funnel"}}
    )
    assert len(state["triggered"]) == 104
    assert len(state["survivors"]) == 44
    assert len(state["disqualified"]) == 60

    summary = json.loads((OUTPUT / "run_summary.json").read_text())
    assert summary["funnel"]["triggered"] == 104
    assert summary["funnel"]["survivors"] == 44
    assert summary["funnel"]["disqualified"] == 60
