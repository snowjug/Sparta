# Sparta developer tasks for Linux, macOS, WSL and Git Bash.
# Windows without `make`: run the same tasks with  powershell -ExecutionPolicy Bypass -File scripts\tasks.ps1 <task>
#
#   make bootstrap     one-time setup (Python environment, web dependencies, .env)
#   make dev           API + web with SQLite and the simulator (open http://localhost:3000/simulator)
#   make check         everything CI checks
#
# Variables you can override:  VENV=path/to/venv  API_PORT=8001  WEB_PORT=3001  IMAGE=my-api-image

SHELL := bash
.DEFAULT_GOAL := help

API_DIR := services/api
WEB_DIR := apps/web
VENV ?= $(API_DIR)/.venv
ifeq ($(OS),Windows_NT)
PY := $(abspath $(VENV))/Scripts/python.exe
else
PY := $(abspath $(VENV))/bin/python
endif
API_PORT ?= 8000
WEB_PORT ?= 3000
IMAGE ?= sparta-api
export SPARTA_VENV := $(abspath $(VENV))

.PHONY: help bootstrap dev dev-docker dev-deps api web test lint typecheck format migrate seed openapi openapi-check \
	eval keygen smoke check lock verify-locks docker-build compose-up compose-down clean venv-check

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Sparta tasks (Windows without make: scripts\\tasks.ps1 <task>)\n\n"} /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv-check:
	@test -x "$(PY)" || { echo "ERROR: the Python environment $(VENV) does not exist yet." >&2; echo "  - Run 'make bootstrap' once (or point VENV=<path> at an existing environment)." >&2; exit 1; }

bootstrap: ## Create the Python environment, install web dependencies, create .env
	@bash scripts/bootstrap.sh

dev: venv-check ## Run API (SQLite, simulator) and web app together; Ctrl+C stops both
	@bash scripts/dev.sh all --api-port $(API_PORT) --web-port $(WEB_PORT)

dev-docker: venv-check ## Same as dev, with PostgreSQL and Redis from docker compose
	@bash scripts/dev.sh all --docker --api-port $(API_PORT) --web-port $(WEB_PORT)

dev-deps: ## Start only PostgreSQL and Redis (docker compose)
	docker compose up -d --wait postgres redis

api: venv-check ## Run only the API
	@bash scripts/dev.sh api --api-port $(API_PORT)

web: ## Run only the web app
	@bash scripts/dev.sh web --api-port $(API_PORT) --web-port $(WEB_PORT)

test: venv-check ## Backend (pytest) and web unit tests
	cd $(API_DIR) && "$(PY)" -X utf8 -m pytest tests
	@if [ -d $(WEB_DIR)/node_modules ]; then cd $(WEB_DIR) && npm test; else echo "web dependencies are not installed: skipping the web tests (run make bootstrap)"; fi

lint: venv-check ## ruff check + ruff format --check (+ eslint when the web dependencies exist)
	cd $(API_DIR) && "$(PY)" -m ruff check .
	cd $(API_DIR) && "$(PY)" -m ruff format --check .
	@if [ -d $(WEB_DIR)/node_modules ]; then cd $(WEB_DIR) && npm run lint; else echo "web dependencies are not installed: skipping eslint"; fi

typecheck: venv-check ## mypy (+ tsc for the web app)
	cd $(API_DIR) && "$(PY)" -m mypy src
	@if [ -d $(WEB_DIR)/node_modules ]; then cd $(WEB_DIR) && npm run typecheck; else echo "web dependencies are not installed: skipping tsc"; fi

format: venv-check ## ruff format + ruff check --fix
	cd $(API_DIR) && "$(PY)" -m ruff format .
	cd $(API_DIR) && "$(PY)" -m ruff check --fix .

migrate: venv-check ## Apply database migrations (SPARTA_DATABASE_URL from .env)
	@bash scripts/dev.sh migrate

seed: venv-check ## Create the development owner
	@bash scripts/dev.sh seed

openapi: venv-check ## Regenerate packages/contracts/openapi.json
	cd $(API_DIR) && "$(PY)" -X utf8 -m sparta openapi

openapi-check: venv-check ## Fail when the committed OpenAPI contract is stale
	cd $(API_DIR) && "$(PY)" -X utf8 -m sparta openapi --check

eval: venv-check ## Evaluation on the dev split (gates on safety invariants; never tune on the test split)
	cd $(API_DIR) && "$(PY)" -X utf8 -m sparta evaluate --split dev

keygen: venv-check ## Print fresh SPARTA_DATA_KEYS / SPARTA_PEPPER / SPARTA_WEBHOOK_SECRET values (nothing is stored)
	@cd $(API_DIR) && "$(PY)" -X utf8 -m sparta keygen

smoke: ## Smoke-test a running API (health, readiness, simulator call)
	@bash scripts/smoke.sh --base-url http://127.0.0.1:$(API_PORT)

check: lint typecheck test openapi-check eval ## Everything CI checks for the backend, plus the web lockfile and build
	@if [ -d $(WEB_DIR)/node_modules ]; then cd $(WEB_DIR) && npm run lock:check && npm run build; else echo "web dependencies are not installed: skipped the web lockfile check and build"; fi

lock: ## Regenerate the hash-pinned image locks (requirements*.lock); needs network access
	@bash scripts/lock.sh

verify-locks: venv-check ## Check that every hash in requirements*.lock is a file digest published on pypi.org (needs network)
	@"$(PY)" scripts/verify_locks.py

docker-build: ## Build the container images (sparta-api and sparta-web); behind a mirror set PIP_INDEX_URL and NPM_REGISTRY
	docker build -t $(IMAGE) $(if $(PIP_INDEX_URL),--build-arg PIP_INDEX_URL=$(PIP_INDEX_URL)) $(API_DIR)
	docker build -t sparta-web $(if $(NPM_REGISTRY),--build-arg NPM_REGISTRY=$(NPM_REGISTRY)) $(WEB_DIR)

compose-up: ## Start the whole stack in Docker (PostgreSQL, Redis, API, web)
	docker compose up -d --build

compose-down: ## Stop the Docker stack (add -v by hand to delete the data volumes: docker compose down -v)
	docker compose down

clean: ## Remove caches and build output (keeps the virtual environment, node_modules and services/api/var)
	rm -rf $(API_DIR)/.pytest_cache $(API_DIR)/.mypy_cache $(API_DIR)/.ruff_cache $(API_DIR)/.hypothesis
	find $(API_DIR)/src $(API_DIR)/tests $(API_DIR)/migrations -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(WEB_DIR)/.next $(WEB_DIR)/test-results $(WEB_DIR)/playwright-report $(WEB_DIR)/coverage
