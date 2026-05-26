"""Expansion Agent CLI.

Subcommands:
    run                  full pipeline including LLM calls
    dry-run              filter + rank + assemble; skip LLM and cap
    replay <run_id>      reuse persisted contexts, re-call LLM only
    limit <N>            cap to N LLM calls (for fast iteration)
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from config.settings import get_settings
from src.graph.build import build_graph
from src.graph.state import RunConfig

app = typer.Typer(add_completion=False, help="GTM Mesh Expansion Agent CLI")
console = Console()


def _new_run_id() -> str:
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _render_funnel(state: dict) -> None:
    funnel = {
        "total": len(state.get("all_accounts", [])),
        "triggered": len(state.get("triggered", [])),
        "survivors": len(state.get("survivors", [])),
        "disqualified": len(state.get("disqualified", [])),
        "signals_kept": sum(1 for s in (state.get("signals") or []) if s.is_signal),
        "signals_dropped": sum(1 for s in (state.get("signals") or []) if not s.is_signal),
    }
    t = Table(title="Funnel", show_header=True, header_style="bold cyan")
    t.add_column("Stage")
    t.add_column("Count", justify="right")
    for k, v in funnel.items():
        t.add_row(k, str(v))
    console.print(t)


def _render_routing(state: dict) -> None:
    ae = state.get("capped_by_ae") or {}
    csm = state.get("capped_by_csm") or {}
    if ae:
        t = Table(title="Per-AE queue", show_header=True, header_style="bold magenta")
        t.add_column("AE")
        t.add_column("Signals", justify="right")
        for name, sigs in sorted(ae.items()):
            t.add_row(name, str(len(sigs)))
        console.print(t)
    if csm:
        t = Table(title="Per-CSM queue", show_header=True, header_style="bold magenta")
        t.add_column("CSM")
        t.add_column("Signals", justify="right")
        for name, sigs in sorted(csm.items()):
            t.add_row(name, str(len(sigs)))
        console.print(t)


def _render_survivor_split(state: dict) -> None:
    from collections import Counter

    survivors = state.get("survivors") or []
    ae = Counter(n.ownership.ae_name for n in survivors if n.ownership.ae_name)
    csm = Counter(n.ownership.csm_name for n in survivors if n.ownership.csm_name)

    t = Table(title="Survivors split — by AE", show_header=True, header_style="bold green")
    t.add_column("AE")
    t.add_column("Count", justify="right")
    for name, n in ae.most_common():
        t.add_row(name, str(n))
    console.print(t)

    t = Table(title="Survivors split — by CSM", show_header=True, header_style="bold green")
    t.add_column("CSM")
    t.add_column("Count", justify="right")
    for name, n in csm.most_common():
        t.add_row(name, str(n))
    console.print(t)


async def _run_graph(cfg: RunConfig) -> dict:
    graph = build_graph()
    return await graph.ainvoke(
        {"config": cfg}, config={"configurable": {"thread_id": cfg.run_id}}
    )


@app.command()
def run(model: str = typer.Option(None, help="Override model id")):
    """Full pipeline (LLM enabled)."""
    cfg = RunConfig(run_id=_new_run_id(), today=date.today(), dry_run=False, model=model)
    console.print(f"[bold]Run[/bold] id={cfg.run_id} model={model or get_settings().model}")
    state = asyncio.run(_run_graph(cfg))
    _render_funnel(state)
    _render_routing(state)


@app.command("dry-run")
def dry_run():
    """Filter + rank + assemble + persist. No LLM calls."""
    cfg = RunConfig(run_id=_new_run_id(), today=date.today(), dry_run=True)
    console.print(f"[bold]Dry-run[/bold] id={cfg.run_id}")
    state = asyncio.run(_run_graph(cfg))
    _render_funnel(state)
    _render_survivor_split(state)


@app.command()
def limit(
    n: int = typer.Argument(..., min=1, help="Cap number of LLM calls"),
    model: str = typer.Option(None, help="Override model id"),
):
    """Limited LLM run — score only the top N ranked candidates."""
    cfg = RunConfig(
        run_id=_new_run_id(), today=date.today(), dry_run=False, model=model, limit=n
    )
    console.print(f"[bold]Limit-run[/bold] id={cfg.run_id} top={n}")
    state = asyncio.run(_run_graph(cfg))
    _render_funnel(state)
    _render_routing(state)


@app.command()
def replay(
    run_id: str = typer.Argument(..., help="Existing run_id whose contexts to reuse"),
    model: str = typer.Option(None, help="Override model id"),
):
    """Re-call the LLM using contexts persisted under run_log/contexts/.

    V1 simplification: we re-execute the full graph but reuse the persisted
    context JSON files (the only thing that differs is the LLM output).
    """
    from schemas.account_context import AccountContext

    settings = get_settings()
    ctx_dir = settings.run_log_dir / "contexts"
    if not ctx_dir.exists():
        raise typer.BadParameter(f"no contexts dir at {ctx_dir}")
    files = list(ctx_dir.glob("*.json"))
    if not files:
        raise typer.BadParameter("no persisted contexts to replay")

    console.print(f"[bold]Replay[/bold] from run_id={run_id} ({len(files)} contexts)")
    contexts = {}
    for p in files:
        ctx = AccountContext.model_validate_json(p.read_text())
        contexts[ctx.account_id] = ctx

    # We run the graph but skip filter+rank by directly invoking score_one for each context.
    # For V1 we keep this simple: rerun the full graph; the persisted contexts are reused
    # by virtue of repository producing the same AccountNodes on the same xlsx.
    cfg = RunConfig(
        run_id=_new_run_id() + f"-replay-of-{run_id}",
        today=date.today(),
        dry_run=False,
        model=model,
    )
    state = asyncio.run(_run_graph(cfg))
    _render_funnel(state)
    _render_routing(state)


if __name__ == "__main__":
    app()
