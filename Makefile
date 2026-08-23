.PHONY: help demo api console test lint ablate dedupe load up up-geo down clean

help:
	@echo "PHAROS"
	@echo ""
	@echo "  make demo       generate scenario, start API and console  (the demo)"
	@echo "  make api        API only, on :8000"
	@echo "  make console    console only, on :5173"
	@echo ""
	@echo "  make ablate     full ablation table, 3 seeds"
	@echo "  make dedupe     naive vs deduplicated demand comparison"
	@echo "  make load       40,000-message throughput test"
	@echo ""
	@echo "  make test       pytest"
	@echo "  make lint       ruff"
	@echo "  make up         Postgres + Redis + MinIO, for the scaled path"

# --- the demo ---------------------------------------------------------------
# Two processes, no containers, no network. The API loads the scenario in the
# background and the console shows its progress.
demo:
	@command -v npm >/dev/null || { echo "node/npm required for the console"; exit 1; }
	@test -d web/console/node_modules || (cd web/console && npm install)
	@echo "API      -> http://localhost:8000/docs"
	@echo "Console  -> http://localhost:5173"
	@trap 'kill 0' EXIT INT TERM; \
	  uv run uvicorn pharos_api.main:app --port 8000 & \
	  (cd web/console && npm run dev) & \
	  wait

api:
	uv run uvicorn pharos_api.main:app --reload --port 8000

console:
	cd web/console && npm run dev

# --- evaluation -------------------------------------------------------------
ablate:
	uv run python -m pharos_sim.cli ablate

dedupe:
	uv run python -m pharos_sim.cli dedupe

load:
	uv run python -m pharos_sim.cli load

scenario:
	uv run python -m pharos_sim.cli run --config $(or $(C),full)

# --- quality ----------------------------------------------------------------
test:
	uv run pytest -q

lint:
	uv run ruff check .

# --- the scaled path (not needed for the demo) ------------------------------
up:
	docker compose up -d db redis minio

up-geo:
	docker compose --profile geo up -d

down:
	docker compose down

clean:
	rm -rf data/results data/*.pkl data/*.db .pytest_cache .ruff_cache
