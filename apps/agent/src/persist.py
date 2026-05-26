"""Persistence layer — writes to run_log/ and output/ per spec §8.

The output JSON files are the data contract for the API. Their shape MUST mirror
what the FastAPI routes return so the API is a dumb passthrough.

In V1.5 this is the only module (alongside repository.py) that swaps to talk to
Postgres. The graph/nodes layer is untouched.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config.csm_roster import slugify
from config.settings import get_settings
from schemas.notification import Notification
from schemas.signal import Signal
from src.graph.state import AgentState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: Any) -> None:
    _ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")


def _json_default(o):
    if isinstance(o, (datetime,)):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "model_dump"):
        return o.model_dump()
    if is_dataclass(o):
        return asdict(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def persist_run(state: AgentState) -> dict:
    """Write everything for one run. Returns a small dict the caller can log."""
    settings = get_settings()
    run_log = _ensure_dir(settings.run_log_dir)
    output = _ensure_dir(settings.output_dir)
    contexts_dir = _ensure_dir(run_log / "contexts")

    cfg = state["config"]
    run_id = cfg.run_id

    all_accounts = state.get("all_accounts") or []
    triggered = state.get("triggered") or []
    survivors = state.get("survivors") or []
    notifications: list[Notification] = state.get("disqualified") or []
    signals: list[Signal] = state.get("signals") or []
    capped_by_ae: dict[str, list[Signal]] = state.get("capped_by_ae") or {}
    capped_by_csm: dict[str, list[Signal]] = state.get("capped_by_csm") or {}
    extras_by_ae: dict[str, list[Signal]] = state.get("extras_by_ae") or {}
    extras_by_csm: dict[str, list[Signal]] = state.get("extras_by_csm") or {}
    contexts = state.get("contexts") or {}
    triggered_at = state.get("triggered_at") or datetime.utcnow()

    # ---- run_log/non_triggered.csv ---------------------------------------
    non_triggered = [n for n in all_accounts if not (n.use_case_gap_field and n.use_case_gap_field.strip())]
    with (run_log / "non_triggered.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["run_id", "account_id_15", "account_name", "ae", "csm"])
        for n in non_triggered:
            w.writerow([run_id, n.account_id_15, n.account_name, n.ownership.ae_name or "", n.ownership.csm_name or ""])

    # ---- run_log/notifications.csv ---------------------------------------
    notif_path = run_log / "notifications.csv"
    write_header = not notif_path.exists() or notif_path.stat().st_size == 0
    with notif_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["run_id", "account_id", "account_name", "ae", "csm", "detected_gap", "disqualifier_rule", "explanation"])
        for n in notifications:
            w.writerow([run_id, n.account_id, n.account_name, n.ae or "", n.csm or "", n.detected_gap, n.disqualifier_rule, n.explanation])

    # ---- run_log/signals.csv ---------------------------------------------
    signals_path = run_log / "signals.csv"
    write_header = not signals_path.exists() or signals_path.stat().st_size == 0
    with signals_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["run_id", "account_id", "account_name", "is_signal", "priority_band", "final_score", "payload_json"])
        for s in signals:
            w.writerow([
                run_id,
                s.account_id,
                s.account_name,
                "true" if s.is_signal else "false",
                s.priority_band or "",
                f"{s.final_score:.4f}" if s.final_score is not None else "",
                s.model_dump_json(),
            ])

    # ---- run_log/contexts/<id>.json --------------------------------------
    # Frozen Claude inputs for the survivors.
    for aid, ctx in contexts.items():
        (contexts_dir / f"{aid}.json").write_text(ctx.model_dump_json(indent=2), encoding="utf-8")
    # Also write a raw AccountNode snapshot for every triggered account, so the
    # /accounts/{id} endpoint can serve the read-only "investigate" view for
    # disqualified accounts too (they never got a Claude context built).
    triggered_by_id = {n.account_id_15: n for n in triggered}
    for aid, node in triggered_by_id.items():
        snap_path = contexts_dir / f"{aid}.json"
        if snap_path.exists():
            continue  # don't overwrite a Claude-ready context with a raw node
        snap_path.write_text(node.model_dump_json(indent=2), encoding="utf-8")

    # ---- run_log/agent_runs.csv ------------------------------------------
    runs_path = run_log / "agent_runs.csv"
    write_header = not runs_path.exists() or runs_path.stat().st_size == 0
    with runs_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["run_id", "triggered_at", "total", "triggered", "survivors", "signals_kept", "signals_dropped", "dry_run"])
        kept = sum(1 for s in signals if s.is_signal)
        w.writerow([
            run_id, triggered_at.isoformat(),
            len(all_accounts), len(triggered), len(survivors), kept, len(signals) - kept,
            "true" if cfg.dry_run else "false",
        ])

    # ---- run_log/outcomes.csv: ensure header exists (filled by API) -------
    outcomes_path = run_log / "outcomes.csv"
    if not outcomes_path.exists() or outcomes_path.stat().st_size == 0:
        with outcomes_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["timestamp", "run_id", "signal_id", "user", "role", "relevant", "actioned", "notes"])

    # ---------- output/ (the API's data contract) -------------------------

    # output/signals.json — kept signals across all roles
    kept_signals = [s for s in signals if s.is_signal]
    _write_json(output / "signals.json", {
        "run_id": run_id,
        "generated_at": triggered_at.isoformat(),
        "signals": [_signal_to_payload(s, run_id) for s in kept_signals],
    })

    # output/queues/by_ae/<slug>.json + by_csm/<slug>.json
    queues_ae = _ensure_dir(output / "queues" / "by_ae")
    queues_csm = _ensure_dir(output / "queues" / "by_csm")
    # Clear any prior files in those dirs (this run is the source of truth)
    for p in queues_ae.glob("*.json"):
        p.unlink()
    for p in queues_csm.glob("*.json"):
        p.unlink()

    for ae_name, sigs in capped_by_ae.items():
        extras = extras_by_ae.get(ae_name, [])
        _write_json(queues_ae / f"{slugify(ae_name)}.json", {
            "user": ae_name,
            "role": "AE",
            "run_id": run_id,
            "signals": [_signal_to_payload(s, run_id) for s in sigs],
            "extras": [_signal_to_payload(s, run_id) for s in extras],  # ranks 6..10
        })
    for csm_name, sigs in capped_by_csm.items():
        extras = extras_by_csm.get(csm_name, [])
        _write_json(queues_csm / f"{slugify(csm_name)}.json", {
            "user": csm_name,
            "role": "CSM",
            "run_id": run_id,
            "signals": [_signal_to_payload(s, run_id) for s in sigs],
            "extras": [_signal_to_payload(s, run_id) for s in extras],
        })

    # output/notifications/by_ae/<slug>.json + by_csm/<slug>.json
    notif_ae_dir = _ensure_dir(output / "notifications" / "by_ae")
    notif_csm_dir = _ensure_dir(output / "notifications" / "by_csm")
    for p in notif_ae_dir.glob("*.json"):
        p.unlink()
    for p in notif_csm_dir.glob("*.json"):
        p.unlink()

    notifs_by_ae: dict[str, list[Notification]] = {}
    notifs_by_csm: dict[str, list[Notification]] = {}
    for n in notifications:
        if n.ae:
            notifs_by_ae.setdefault(n.ae, []).append(n)
        if n.csm:
            notifs_by_csm.setdefault(n.csm, []).append(n)

    for ae_name, ns in notifs_by_ae.items():
        _write_json(notif_ae_dir / f"{slugify(ae_name)}.json", {
            "user": ae_name, "role": "AE", "run_id": run_id,
            "notifications": [n.model_dump() for n in ns],
        })
    for csm_name, ns in notifs_by_csm.items():
        _write_json(notif_csm_dir / f"{slugify(csm_name)}.json", {
            "user": csm_name, "role": "CSM", "run_id": run_id,
            "notifications": [n.model_dump() for n in ns],
        })

    # output/run_summary.json — the dashboard payload for RevOps
    funnel = {
        "total": len(all_accounts),
        "triggered": len(triggered),
        "survivors": len(survivors),
        "disqualified": len(notifications),
        "signals_kept": sum(1 for s in signals if s.is_signal),
        "signals_dropped": sum(1 for s in signals if not s.is_signal),
    }
    from collections import Counter
    dq_breakdown = Counter(n.disqualifier_rule for n in notifications)
    by_ae_counts = {ae: len(sigs) for ae, sigs in capped_by_ae.items()}
    by_csm_counts = {csm: len(sigs) for csm, sigs in capped_by_csm.items()}
    _write_json(output / "run_summary.json", {
        "run_id": run_id,
        "triggered_at": triggered_at.isoformat(),
        "dry_run": cfg.dry_run,
        "funnel": funnel,
        "dq_breakdown": dict(dq_breakdown),
        "queues": {"by_ae": by_ae_counts, "by_csm": by_csm_counts},
    })

    # output/runs.json — append/replace listing (single-run V1)
    runs_index = output / "runs.json"
    runs_list: list[dict] = []
    if runs_index.exists():
        try:
            runs_list = json.loads(runs_index.read_text(encoding="utf-8")).get("runs", [])
        except (json.JSONDecodeError, OSError):
            runs_list = []
    runs_list = [r for r in runs_list if r.get("run_id") != run_id]
    runs_list.append({
        "run_id": run_id,
        "triggered_at": triggered_at.isoformat(),
        "funnel": funnel,
        "dry_run": cfg.dry_run,
    })
    runs_list.sort(key=lambda r: r["triggered_at"], reverse=True)
    _write_json(runs_index, {"runs": runs_list})

    return {"run_id": run_id, "funnel": funnel}


def _signal_to_payload(s: Signal, run_id: str) -> dict:
    """API-facing shape: signal JSON + a synthesized id for routing."""
    payload = s.model_dump()
    payload["id"] = f"{run_id}:{s.account_id}"
    return payload


def record_outcome(
    *, run_id: str, signal_id: str, user: str, role: str,
    relevant: bool | None, actioned: bool | None, notes: str = "",
) -> None:
    """Appends to outcomes.csv. Called by the FastAPI /api/feedback endpoint."""
    settings = get_settings()
    path = _ensure_dir(settings.run_log_dir) / "outcomes.csv"
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                ["timestamp", "run_id", "signal_id", "user", "role", "relevant", "actioned", "notes"]
            )
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            datetime.utcnow().isoformat(),
            run_id, signal_id, user, role,
            "" if relevant is None else ("true" if relevant else "false"),
            "" if actioned is None else ("true" if actioned else "false"),
            notes,
        ])
