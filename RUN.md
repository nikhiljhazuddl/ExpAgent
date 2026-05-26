# RUN.md — GTM Mesh Expansion Agent V1

This file is the operator's handbook. The full design lives in
[docs/Expansion_Agent_V1_Build_Spec.md](docs/Expansion_Agent_V1_Build_Spec.md);
the *why* is in [docs/agent_brain.md](docs/agent_brain.md).

---

## 1 · Prerequisites

| Tool | Version | Why |
|---|---|---|
| Python | 3.11 or 3.12 | agent + api |
| Node | 20+ | web |
| `uv` | latest | manages the two Python projects |
| `pnpm` | 9+ | web deps. Install via `npm install -g --prefix ~/.local pnpm` if corepack is blocked. |

Check the toolchain in one shot:

```bash
make scaffold-check
```

## 2 · Environment

Copy `.env.example` to `.env` and fill in:

```env
ANTHROPIC_API_KEY=sk-ant-...
RUN_COST_CAP_USD=5
MAX_CONCURRENCY=8
MODEL=claude-opus-4-7
```

The agent reads from both `apps/agent/.env` and the repo-root `.env`. The
dataset path resolves to `data/Expansion_Agent_1.xlsx` by default — override
with `DATA_XLSX_PATH` if you move it.

## 3 · First-run instructions

```bash
# install everything once
make install

# 1. funnel sanity check — no LLM, ~4s
make agent-dry
# expected output (rendered with rich):
#   Funnel: total=117 triggered=104 survivors=44 disqualified=60
#   Survivors split — by AE   : Bhargav 21 · Brooks 16 · Mark 6 · Paul 1
#   Survivors split — by CSM  : Janhvi 23 · Aastha 11 · Saumitra 6 · Joe 4

# 2. limited LLM run — 3 accounts, ~30s
cd apps/agent && uv run python -m cli limit 3

# 3. full LLM run — 44 calls, ~3–5 min
cd apps/agent && uv run python -m cli run

# 4. bring up the app — API :8000, web :3000
cd ../.. && make dev
# open http://localhost:3000/login
```

## 4 · Output files (the data contract)

```
apps/agent/output/
├── signals.json                       all kept signals from the latest run
├── runs.json                          list of historical runs (V1: single-run)
├── run_summary.json                   funnel + DQ breakdown + queue depth
├── queues/
│   ├── by_ae/<slug>.json              per-AE top-N capped queue
│   └── by_csm/<slug>.json             per-CSM top-N capped queue
└── notifications/
    ├── by_ae/<slug>.json              per-AE transparency log
    └── by_csm/<slug>.json             per-CSM transparency log
```

```
apps/agent/run_log/
├── agent_runs.csv                     one row per run, with funnel summary
├── signals.csv                        every signal kept + dropped, JSON payload column
├── notifications.csv                  every disqualifier hit, append-only
├── non_triggered.csv                  accounts with no use-case gap (the 13 that didn't trigger)
├── data_quality.csv                   join misses + missing fields + ambiguous values
├── outcomes.csv                       feedback from /api/feedback (Mark Relevant / Actioned)
└── contexts/<account_id_15>.json      frozen AccountContext for each scored survivor
```

**Reading the output:**
- The web app reads `output/*.json` via the API and never touches `run_log/` directly. `run_log/` is the audit/replay store.
- `signals.json` is the master list. Each row carries an `id = "<run_id>:<account_id_15>"`.
- The `*.csv` files in `run_log/` are append-only across runs — useful for backtests once V1.5 historical data lands.

## 5 · Replay a previous run

```bash
cd apps/agent
uv run python -m cli replay 20260518-124423
```

Replay reuses the persisted `contexts/<id>.json` payloads (so context assembly is
free) and re-issues the LLM calls. Useful when iterating on the prompt or the
output schema without re-paying for context assembly.

## 6 · The CLI

| Command | Purpose | LLM? |
|---|---|---|
| `uv run python -m cli dry-run` | filter + rank + assemble + persist | no |
| `uv run python -m cli limit N` | dry-run + score top N | yes, capped |
| `uv run python -m cli run` | full run | yes |
| `uv run python -m cli replay <run_id>` | re-score using persisted contexts | yes |

All four write to `run_log/` and `output/` on success. The API picks up the
new files on the next request — no restart needed.

## 7 · Web app

```bash
make dev                          # API on :8000, web on :3000
open http://localhost:3000/login  # pick role + name → cookie-based session
```

| Page | Notes |
|---|---|
| `/login` | dropdown populated from `GET /api/users` (auto-discovers AEs+CSMs from output) |
| `/dashboard` | role-aware: AE/CSM see top 5 capped signals; RevOps/Admin sees funnel + per-role queue depth |
| `/signal/[id]` | full signal: 5 sections + sticky metadata + draft outreach with Copy + Mark Relevant/Actioned buttons |
| `/notifications` | the transparency log — AE/CSM see only their accounts, RevOps sees all |
| `/accounts/[id]` | read-only frozen AccountContext (useful when investigating a dropped account) |
| `/runs` | RevOps/Admin only — list of historical runs |

There is **no auth** in V1; the cookie is intentionally trivial. Auth lands in V1.5.

## 8 · Operational notes

- **Cost cap.** `RUN_COST_CAP_USD=5` — the spec budget. Full run is ~265k input + 66k output tokens. The cap is advisory in V1; enforce it externally if needed.
- **Concurrency.** `MAX_CONCURRENCY=8` — passed to LangGraph's `Send` fan-out.
- **Idempotency.** `run_id = YYYYMMDD-HHMMSS`. Re-running on the same data is safe.
- **Hot reload.** API runs under `uvicorn --reload`; web runs under `next dev`. Edit and save — no restart.

## 9 · Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `make agent-dry` shows wrong funnel | xlsx changed | `pytest tests/test_filter.py` will pinpoint which DQ count drifted |
| `ANTHROPIC_API_KEY not set` | `.env` not loaded | check both `apps/agent/.env` and repo-root `.env`; `uv run` reads both |
| `signals (revops): 0` after `make agent-run` | LLM call failed silently | inspect `apps/agent/run_log/signals.csv` — the `payload_json` column has `reasoning_trace` for every account |
| API can't find files | working dir wrong | `cd apps/api && uv run uvicorn main:app` (relative paths resolve to `apps/agent/output`) |
| pnpm missing | corepack blocked | `npm install -g --prefix ~/.local pnpm && export PATH=~/.local/bin:$PATH` |

## 10 · V1.5 migration plan

V1.5 swaps the filesystem for Postgres + pgvector. **The LangGraph nodes do not change** — only the two adapter modules:

| V1 module | V1.5 change |
|---|---|
| `apps/agent/src/repository.py` | swap `pd.read_excel` for `SELECT` queries against `accounts`, `account_facts`, `contacts`, `gong_calls`; preserve the `AccountNode` shape exactly. The `load_accounts()` signature is the contract. |
| `apps/agent/src/persist.py` | `persist_run` keeps its arg, swaps the file writes for INSERTs against `agent_runs`, `signals`, `account_events`, `account_snapshots`, `outcomes` (see spec §8 mapping table). |
| `apps/agent/src/graph/build.py` | one line: replace `MemorySaver()` with `PostgresSaver(...)` so checkpoints survive a restart. |

No change in:
- `apps/agent/src/filter_logic.py`, `rank_logic.py`, `context_builder.py`, `reasoning.py`
- `apps/agent/schemas/*` (Pydantic models stay the source of truth)
- `apps/agent/src/graph/{state,nodes}.py` (state is still the contract — the checkpointer just persists it differently)
- The FastAPI layer keeps reading from `output/*.json`; in V1.5 we add a thin `repository_api.py` that materializes the same JSON shape from queries, then delete the file-reading path.

The frontend never notices. By design.

## 11 · Test suite

```bash
cd apps/agent && uv run pytest -v
# expected: 43 passed across schemas / repository / filter (HARD GATE) /
#           rank / context / reasoning / graph
cd ../api    && uv run pytest -v
# expected: 6 passed across the API surface
```

The **HARD GATE** is `tests/test_filter.py::test_funnel_exact`. If that fails, stop and reconcile the spec vs the data before any code change.

---

*Generated in Phase 13 of the V1 build. See git history for build provenance.*
