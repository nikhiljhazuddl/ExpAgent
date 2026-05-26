.PHONY: scaffold-check agent-run agent-dry agent-limit api web dev install clean

PY := uv run python

scaffold-check:
	@command -v uv >/dev/null || (echo "uv missing: https://docs.astral.sh/uv" && exit 1)
	@command -v pnpm >/dev/null || (echo "pnpm missing: 'corepack enable && corepack prepare pnpm@latest --activate'" && exit 1)
	@test -f data/Expansion_Agent_1.xlsx || (echo "dataset missing at data/Expansion_Agent_1.xlsx" && exit 1)
	@test -f .env || echo "warning: .env not present (copy from .env.example)"
	@echo "scaffold ok"

install:
	cd apps/agent && uv sync
	cd apps/api && uv sync
	cd apps/web && pnpm install

agent-run:
	cd apps/agent && $(PY) -m cli run

agent-dry:
	cd apps/agent && $(PY) -m cli dry-run

agent-limit:
	cd apps/agent && $(PY) -m cli limit $(N)

api:
	cd apps/api && uv run uvicorn main:app --reload --port 8000

web:
	cd apps/web && pnpm dev

dev:
	@echo "starting API on :8000 and web on :3000"
	$(MAKE) -j2 api web

clean:
	rm -rf apps/agent/run_log/* apps/agent/output/*
