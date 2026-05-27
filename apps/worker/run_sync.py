"""Master sync orchestrator.

Usage:
    # First time — seed from CSV, then sync all platforms
    uv run python run_sync.py --seed --all

    # Subsequent runs (every 15 min via cron / Render cron job)
    uv run python run_sync.py --all

    # Individual platforms
    uv run python run_sync.py --csv --sf --hs --gong --fireflies --pylon --linear

    # Continuous loop (default interval: 15 min)
    uv run python run_sync.py --all --loop
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("run_sync")

INTERVAL = 15 * 60  # 15 minutes


def run_csv() -> None:
    from sync.csv_importer import run
    run()


def run_sf() -> None:
    from sync.salesforce_sync import run
    run()


def run_hs() -> None:
    from sync.hubspot_sync import run
    run()


def run_gong() -> None:
    from sync.gong_sync import run
    run()


def run_fireflies() -> None:
    from sync.fireflies_sync import run
    run()


def run_pylon() -> None:
    from sync.pylon_sync import run
    run()


def run_linear() -> None:
    from sync.linear_sync import run
    run()


RUNNERS = {
    "csv":       run_csv,
    "sf":        run_sf,
    "hs":        run_hs,
    "gong":      run_gong,
    "fireflies": run_fireflies,
    "pylon":     run_pylon,
    "linear":    run_linear,
}


def run_selected(selected: list[str]) -> None:
    for name in selected:
        fn = RUNNERS.get(name)
        if not fn:
            continue
        try:
            log.info("▶ starting %s sync…", name)
            fn()
            log.info("✓ %s sync complete", name)
        except Exception as exc:
            log.error("✗ %s sync failed: %s", name, exc, exc_info=True)


def main() -> None:
    p = argparse.ArgumentParser(description="GTM Mesh IQ — unified sync runner")
    p.add_argument("--seed",      action="store_true", help="Import CSV seed data (run once)")
    p.add_argument("--all",       action="store_true", help="Run all platform syncs")
    p.add_argument("--csv",       action="store_true")
    p.add_argument("--sf",        action="store_true")
    p.add_argument("--hs",        action="store_true")
    p.add_argument("--gong",      action="store_true")
    p.add_argument("--fireflies", action="store_true")
    p.add_argument("--pylon",     action="store_true")
    p.add_argument("--linear",    action="store_true")
    p.add_argument("--loop",      action="store_true", help="Run continuously every 15 min")
    p.add_argument("--interval",  type=int, default=INTERVAL, help="Loop interval in seconds")
    args = p.parse_args()

    selected: list[str] = []
    if args.seed or args.csv:
        selected.append("csv")
    if args.all or args.sf:
        selected.append("sf")
    if args.all or args.hs:
        selected.append("hs")
    if args.all or args.gong:
        selected.append("gong")
    if args.all or args.fireflies:
        selected.append("fireflies")
    if args.all or args.pylon:
        selected.append("pylon")
    if args.all or args.linear:
        selected.append("linear")

    if not selected:
        p.print_help()
        sys.exit(1)

    run_selected(selected)

    if args.loop:
        interval = args.interval
        while True:
            # CSV seed is one-time only — skip in loop
            loop_selected = [s for s in selected if s != "csv"]
            log.info("sleeping %ds until next sync…", interval)
            time.sleep(interval)
            run_selected(loop_selected)


if __name__ == "__main__":
    main()
