#!/bin/bash
# Watches SF sync completion, then runs the agent automatically.
# Usage: bash watch_and_run.sh &

set -a
source "$(dirname "$0")/.env"
set +a

AGENT_DIR="$(dirname "$0")/apps/agent"
WORKER_DIR="$(dirname "$0")/apps/worker"
THRESHOLD=20000   # consider sync "done enough" at 20k+ accounts
CHECK_INTERVAL=300  # check every 5 minutes
LOG="$(dirname "$0")/watch_and_run.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Watcher started. Will run agent when sf_accounts_raw >= $THRESHOLD rows ==="

while true; do
    COUNT=$(cd "$AGENT_DIR" && uv run python -c "
import os, sys
sys.path.insert(0, '.')
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_ROLE_KEY'])
r = sb.table('sf_accounts_raw').select('account_id', count='exact').execute()
print(r.count)
" 2>/dev/null)

    log "sf_accounts_raw count: ${COUNT:-error}"

    if [ -n "$COUNT" ] && [ "$COUNT" -ge "$THRESHOLD" ]; then
        log "✅ Sync threshold reached ($COUNT accounts). Running agent..."

        # Also run Gong + Fireflies sync to get latest conversation data
        log "Running Gong + Fireflies sync first..."
        cd "$WORKER_DIR" && uv run python run_sync.py --gong --fireflies >> "$LOG" 2>&1
        log "Conversation sync done."

        # Now run the agent
        log "Running agent (cli.py run)..."
        cd "$AGENT_DIR" && uv run python cli.py run >> "$LOG" 2>&1
        EXIT_CODE=$?

        if [ $EXIT_CODE -eq 0 ]; then
            log "🎉 Agent completed successfully! Signals are ready."
        else
            log "⚠️  Agent exited with code $EXIT_CODE. Check $LOG for details."
        fi
        break
    fi

    # If sync process died, restart it
    if ! pgrep -f "run_sync.py" > /dev/null; then
        log "⚠️  Sync process not running — restarting SF + Pylon sync..."
        cd "$WORKER_DIR" && uv run python run_sync.py --sf --pylon >> "$LOG" 2>&1 &
        log "Sync restarted (PID $!)."
    fi

    sleep $CHECK_INTERVAL
done

log "=== Watcher done ==="
