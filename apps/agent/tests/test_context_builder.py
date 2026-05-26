"""Snapshot-style test for the context builder against a known survivor."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.context_builder import CHAR_CAP, build_context
from src.filter_logic import run_filter
from src.rank_logic import rank_survivors
from src.repository import Repository

XLSX = Path(__file__).resolve().parent.parent.parent.parent / "data" / "Expansion_Agent_1.xlsx"
TODAY = date(2026, 5, 18)


@pytest.fixture(scope="module")
def top_candidate():
    repo = Repository(XLSX)
    nodes = repo.load_accounts()
    result = run_filter(nodes, TODAY)
    ranked = rank_survivors(result.survivors, TODAY)
    return ranked[0]


def test_builds_context_for_top_candidate(top_candidate):
    ctx = build_context(top_candidate.node, top_candidate.priority_score, TODAY)
    # Basic shape
    assert ctx.account_id == top_candidate.node.account_id_15
    assert ctx.account_name == top_candidate.node.account_name
    assert ctx.ownership.ae.name is not None
    assert ctx.ownership.csm.name is not None
    assert ctx.current_state.use_case_gap_field is not None
    assert ctx.deterministic_priority_score == pytest.approx(top_candidate.priority_score)


def test_token_cap_respected(top_candidate):
    ctx = build_context(top_candidate.node, top_candidate.priority_score, TODAY)
    size = len(ctx.model_dump_json())
    assert size <= CHAR_CAP, f"context too large: {size} > {CHAR_CAP}"


def test_all_survivors_fit_under_cap():
    repo = Repository(XLSX)
    nodes = repo.load_accounts()
    result = run_filter(nodes, TODAY)
    ranked = rank_survivors(result.survivors, TODAY)
    for cand in ranked:
        ctx = build_context(cand.node, cand.priority_score, TODAY)
        size = len(ctx.model_dump_json())
        assert size <= CHAR_CAP, f"{cand.node.account_name}: {size} > {CHAR_CAP}"
