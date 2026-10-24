# Development commands. Everything is project-local: the backend lives in a venv under
# backend/.venv and the frontend in frontend/node_modules. Nothing is installed globally.

PY        := python3
VENV      := backend/.venv
BIN       := $(VENV)/bin
PYTEST    := $(BIN)/python -m pytest
DEMO      ?= $(firstword $(wildcard data/fixtures/*.dem))

.PHONY: help setup setup-backend setup-frontend dev-backend dev-frontend run build \
        test test-backend test-frontend test-integration lint lint-backend lint-frontend \
        format lock fixture warm-maps verify-ui clean clean-data

help:
	@echo "Setup"
	@echo "  make setup             create the venv, install backend and frontend deps"
	@echo ""
	@echo "Run (two terminals in development)"
	@echo "  make dev-backend       API on :8000, with reload"
	@echo "  make dev-frontend      UI on :5173, proxying /api to the backend"
	@echo "  make build && make run single-origin production mode on :8000"
	@echo ""
	@echo "Check"
	@echo "  make test              backend unit+API tests, then frontend tests"
	@echo "  make test-integration  tests against a real demo (needs 'make fixture')"
	@echo "  make lint              ruff, mypy --strict, eslint, tsc"
	@echo "  make verify-ui         drive the built UI in a real browser (server must be up)"
	@echo ""
	@echo "Data"
	@echo "  make fixture           download the public test demo (84 MB, gitignored)"
	@echo "  make warm-maps         pre-download map radar images"
	@echo "  make clean-data        delete all stored demos and analytics"

# --- setup -----------------------------------------------------------------
setup: setup-backend setup-frontend

setup-backend:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install --quiet --upgrade pip
	$(BIN)/pip install --quiet -r backend/requirements.lock
	@echo "backend ready: $$($(BIN)/python --version)"

setup-frontend:
	cd frontend && npm ci
	@echo "frontend ready"

# Regenerate the lockfile from requirements-dev.in. The lockfile is the full pinned
# transitive closure, so an install is reproducible without a resolver.
lock:
	$(BIN)/pip install --quiet -r backend/requirements-dev.in
	$(BIN)/pip freeze --exclude-editable > backend/requirements.lock
	@echo "wrote backend/requirements.lock"

# --- run -------------------------------------------------------------------
# One uvicorn worker, deliberately: the parse supervisor is per-process, so a second
# worker would mean two queues racing for the same rows.
dev-backend:
	cd backend && $(CURDIR)/$(BIN)/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

run:
	cd backend && CS2A_SERVE_FRONTEND=true $(CURDIR)/$(BIN)/uvicorn app.main:app --host 127.0.0.1 --port 8000

# --- check -----------------------------------------------------------------
test: test-backend test-frontend

test-backend:
	cd backend && $(CURDIR)/$(PYTEST) tests/unit tests/api -q

test-frontend:
	cd frontend && npm run test

test-integration:
	@test -n "$(DEMO)" || (echo "no demo fixture; run 'make fixture'" && exit 1)
	cd backend && $(CURDIR)/$(PYTEST) -m fixture_demo -q

lint: lint-backend lint-frontend

lint-backend:
	cd backend && $(CURDIR)/$(BIN)/ruff check .
	cd backend && $(CURDIR)/$(BIN)/ruff format --check .
	cd backend && $(CURDIR)/$(BIN)/mypy app

lint-frontend:
	cd frontend && npx tsc --noEmit && npx eslint .

format:
	cd backend && $(CURDIR)/$(BIN)/ruff check --fix . && $(CURDIR)/$(BIN)/ruff format .

verify-ui:
	@test -n "$(DEMO)" || (echo "no demo fixture; run 'make fixture'" && exit 1)
	cd frontend && node scripts/verify-ui.mjs http://127.0.0.1:8000 $(CURDIR)/$(DEMO) ui-shots

# --- data ------------------------------------------------------------------
fixture:
	cd backend && $(CURDIR)/$(BIN)/python -m app.cli fetch-fixture

warm-maps:
	cd backend && $(CURDIR)/$(BIN)/python -m app.cli warm-maps

clean:
	rm -rf frontend/dist frontend/ui-shots
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/.mypy_cache

# Deletes every stored demo and all derived analytics. Keeps downloaded test fixtures.
clean-data:
	rm -rf data/demos data/tmp data/app.db data/app.db-wal data/app.db-shm
	@echo "stored demos and analytics removed"
