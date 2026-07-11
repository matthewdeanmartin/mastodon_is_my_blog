application_destroy:
	echo
application_deploy:
	echo
application_describe:
	echo:
application_derive_data:
	echo
application_detach:
	echo

.DEFAULT_GOAL := help
UV ?= uv
MAKEFLAGS += --no-print-directory
export PYTHONUTF8 := 1

.PHONY: help install install-backend install-frontend install-blog build-blog serve-blog dev dev-sqlite dev-backend dev-backend-sqlite dev-server-mode dev-server-mode-sqlite dev-mock dev-frontend build build-wheel build-wheel-skip-ng publish publish-test install-from-wheel test test-backend test-frontend test-frontend-integration lint lint-check lint-backend lint-frontend lint-frontend-strict format format-check format-backend format-frontend typecheck security audit-backend check check-ci prerelease prerelease-backend prerelease-frontend clean setup db-reset

POSTGRES_URL ?= postgresql://postgres:xyzzy@localhost:5432/mimb

# Default target
help:
	@echo "Mastodon is My Blog - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              - First-time setup (install dependencies + create .env)"
	@echo "  make install            - Install all dependencies (backend + frontend)"
	@echo "  make install-backend    - Install Python dependencies"
	@echo "  make install-frontend   - Install Node dependencies"
	@echo "  make install-blog       - Install Eleventy blog dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make dev                - Run backend on Postgres + frontend"
	@echo "  make dev-sqlite         - Run backend on SQLite + frontend"
	@echo "  make dev-backend        - Run FastAPI development server on Postgres"
	@echo "  make dev-backend-sqlite - Run FastAPI development server on SQLite"
	@echo "  make dev-server-mode    - Run hosted multi-tenant server on Postgres"
	@echo "  make dev-server-mode-sqlite - Run hosted multi-tenant server on SQLite"
	@echo "  make dev-frontend       - Run Angular development server"
	@echo ""
	@echo "Database:"
	@echo "  make db-reset           - Delete and recreate database"
	@echo ""
	@echo "Build:"
	@echo "  make build              - Build frontend for production"
	@echo "  make build-blog         - Build the Eleventy blog into docs/"
	@echo "  make serve-blog         - Serve the Eleventy blog locally"
	@echo ""
	@echo "Testing:"
	@echo "  make test               - Run all tests (unit only)"
	@echo "  make test-backend       - Run backend tests"
	@echo "  make test-frontend      - Run frontend unit tests (no server needed)"
	@echo "  make test-frontend-integration - Run frontend tests against a live backend"
	@echo "  make test-integration   - Run mastodon_mock-backed backend integration tests"
	@echo "  make format             - Auto-format Python and Angular sources"
	@echo "  make format-check       - Check formatting without changing files"
	@echo "  make lint               - Lint Python and both Angular clients"
	@echo "  make typecheck          - Type-check the Python API"
	@echo "  make security           - Audit Python and npm dependencies"
	@echo "  make check              - Full local quality gate (read-only)"
	@echo "  make check-ci           - CI quality gate (same read-only checks)"
	@echo ""
	@echo "Performance (rtd/reference/ensuring_mimb_stays_fast.md):"
	@echo "  make perf-smoke         - Short perf checks vs mastodon_mock (also runs in CI)"
	@echo "  make perf-seed          - Build a ~1GB local sqlite perf database (once)"
	@echo "  make perf-baseline-sqlite  - Save benchmark baseline (sqlite+duckdb)"
	@echo "  make perf-check-sqlite  - Compare against baseline; fail on big regressions"
	@echo "  make perf-seed-postgres / perf-baseline-postgres / perf-check-postgres"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              - Remove build artifacts and caches"
	@echo ""
	@echo "Distribution:"
	@echo "  make build-wheel        - Build Angular + Python wheel (full)"
	@echo "  make build-wheel-skip-ng - Build wheel reusing existing Angular dist"
	@echo "  make prerelease         - Run strict release checks before publishing"
	@echo "  make publish-test       - Upload wheel to TestPyPI"
	@echo "  make publish            - Upload wheel to PyPI"
	@echo "  make install-from-wheel - Install local wheel and smoke-test"

# First-time setup
setup: install
	@echo "Creating .env file from template..."
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ Created .env file - please edit it with your Mastodon credentials"; \
	else \
		echo "✓ .env file already exists"; \
	fi
	@echo ""
	@echo "Next steps:"
	@echo "  1. Edit .env with your Mastodon app credentials"
	@echo "  2. Run 'make dev' to start development servers"

# Install all dependencies
install: install-backend install-frontend

# Install backend dependencies
install-backend:
	@echo "Installing Python dependencies..."
	$(UV) sync --all-extras
	@echo "✓ Backend dependencies installed"

# Install frontend dependencies
install-frontend:
	@echo "Installing Node dependencies..."
	cd web && npm install
	@echo "✓ Frontend dependencies installed"

# Install blog dependencies
install-blog:
	@echo "Installing Eleventy blog dependencies..."
	npm --prefix docs-src install
	@echo "✓ Blog dependencies installed"

# Run both servers as Git Bash background jobs. If either server exits, stop
# the other one too; Ctrl+C follows the same cleanup path.
define run_dev_servers
	@trap 'kill $$backend_pid $$frontend_pid 2>/dev/null || true' INT TERM EXIT; \
		make $(1) & backend_pid=$$!; \
		make dev-frontend & frontend_pid=$$!; \
		wait -n $$backend_pid $$frontend_pid; status=$$?; \
		kill $$backend_pid $$frontend_pid 2>/dev/null || true; \
		wait $$backend_pid $$frontend_pid 2>/dev/null || true; \
		trap - INT TERM EXIT; \
		exit $$status
endef

dev:
	@echo "Starting backend and frontend servers..."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:4200"
	@echo ""
	$(call run_dev_servers,dev-backend)

dev-sqlite:
	@echo "Starting SQLite backend and frontend servers..."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:4200"
	@echo ""
	$(call run_dev_servers,dev-backend-sqlite)

# Run backend development server
dev-backend:
	@echo "Starting FastAPI server on http://localhost:8000 (Postgres: mimb)"
	DB_URL= DB_BACKEND=postgres APP_POSTGRES_URL="$(POSTGRES_URL)" \
		$(UV) run python -m uvicorn mastodon_is_my_blog.main:app --reload --host 0.0.0.0 --port 8000

dev-backend-sqlite:
	@echo "Starting FastAPI server on http://localhost:8000 (SQLite: app.db)"
	DB_BACKEND=sqlite DB_URL="sqlite+aiosqlite:///./app.db" \
		$(UV) run python -m uvicorn mastodon_is_my_blog.main:app --reload --host 0.0.0.0 --port 8000

# Run the backend as the HOSTED multi-tenant product server (MIMB_MODE=server),
# wired for the mimb_co control plane (spec/paid_hosting/hosted_wiring.md).
# All values are LOCAL DEV defaults; override via environment for anything real.
# Pair with `make serve-hosted` in C:\github\mimb_co.
dev-server-mode:
	@echo "Starting mimb product server (server mode, Postgres) on http://localhost:8000"
	MIMB_MODE=server \
	DB_URL= \
	DB_BACKEND=postgres \
	APP_POSTGRES_URL="$(POSTGRES_URL)" \
	SESSION_SIGNING_KEY=$${SESSION_SIGNING_KEY:-dev-insecure-signing-key-change-me} \
	TOKEN_ENCRYPTION_KEY=$${TOKEN_ENCRYPTION_KEY:-FzAkGyqDKck9qAqt4gcqV1ekRkLHECau1ztHVgT-Iig=} \
	APP_BASE_URL=$${APP_BASE_URL:-http://localhost:8000} \
	HANDOFF_SHARED_SECRET=$${HANDOFF_SHARED_SECRET:-dev-handoff-secret} \
	EXPORT_DIR=$${EXPORT_DIR:-exports} \
	ACCOUNT_PORTAL_URL=$${ACCOUNT_PORTAL_URL:-http://localhost:8051} \
	FRONTEND_URL=$${FRONTEND_URL:-http://localhost:8000} \
	$(UV) run python -m uvicorn mastodon_is_my_blog.main:app --host 127.0.0.1 --port 8000

dev-server-mode-sqlite:
	@echo "Starting mimb product server (server mode, SQLite) on http://localhost:8000"
	@if [ -f mimb_server.db ]; then \
	  mkdir -p backups; \
	  cp mimb_server.db "backups/mimb_server.$$(date +%Y%m%d-%H%M%S).db"; \
	  ls -1t backups/mimb_server.*.db 2>/dev/null | tail -n +11 | xargs -r rm --; \
	  echo "backed up mimb_server.db -> backups/"; \
	fi
	MIMB_MODE=server \
	DB_URL="sqlite+aiosqlite:///mimb_server.db" \
	SESSION_SIGNING_KEY=$${SESSION_SIGNING_KEY:-dev-insecure-signing-key-change-me} \
	TOKEN_ENCRYPTION_KEY=$${TOKEN_ENCRYPTION_KEY:-FzAkGyqDKck9qAqt4gcqV1ekRkLHECau1ztHVgT-Iig=} \
	APP_BASE_URL=$${APP_BASE_URL:-http://localhost:8000} \
	HANDOFF_SHARED_SECRET=$${HANDOFF_SHARED_SECRET:-dev-handoff-secret} \
	EXPORT_DIR=$${EXPORT_DIR:-exports} \
	ACCOUNT_PORTAL_URL=$${ACCOUNT_PORTAL_URL:-http://localhost:8051} \
	FRONTEND_URL=$${FRONTEND_URL:-http://localhost:8000} \
	$(UV) run python -m uvicorn mastodon_is_my_blog.main:app --host 127.0.0.1 --port 8000
# FRONTEND_URL is pinned because a local-dev .env (FRONTEND_URL=:4200 for
# ng serve) would otherwise leak into server mode via load_dotenv and send
# the post-OAuth redirect to the wrong app.

# Run a seeded fake Mastodon instance (the mastodon_mock test dep) for dev.
# Too early to point dev at mastodon.social: Connect Account in the product UI
# works against http://localhost:3000 instead — full OAuth (app registration,
# account-picker authorize page, code exchange) with zero live credentials.
# --demo seeds a small community; state is in-memory, reset on restart.
# Part of mimb_co's `make serve-hosted` stack.
dev-mock:
	@echo "Starting mastodon_mock (seeded demo Mastodon) on http://localhost:3000"
	uv run mastodon_mock serve --in-memory --demo --host 127.0.0.1 --port 3000

# Run frontend development server
dev-frontend:
	@echo "Starting Angular dev server on http://localhost:4200"
	cd web && ng serve web --port 4200 --open

# Build Angular frontend for production only (no Python wheel)
build:
	@echo "Building Angular frontend for production..."
	cd web && ng build web --configuration production
	@echo "✓ Build complete: web/dist/"

# Build Angular + Python distributions (full distribution build)
build-wheel:
	@echo "Building Angular + Python distributions..."
	./scripts/build.sh
	@echo "✓ Distributions built in dist/"

# Build Python distributions reusing existing compiled Angular assets
build-wheel-skip-ng:
	@echo "Building Python distributions (reusing existing Angular assets)..."
	./scripts/build.sh --skip-ng
	@echo "✓ Distributions built in dist/"


# Install local wheel and smoke-test the CLI
install-from-wheel:
	@echo "Installing from local wheel..."
	pip install --force-reinstall dist/*.whl
	mastodon_is_my_blog version
	mastodon_is_my_blog db-info

build-blog: install-blog
	@echo "Building Eleventy blog into docs/..."
	npm --prefix docs-src run build
	@echo "✓ Blog build complete: docs/"

serve-blog: install-blog
	@echo "Serving Eleventy blog on http://localhost:8080"
	npm --prefix docs-src run serve -- --port 8080

# Run all tests
test: test-backend test-frontend

# Run backend tests
test-backend:
	@echo "Running backend tests..."
	uv run python -m pytest test -q --tb=line --no-header --cov-report=html \
		--color=no --cov=mastodon_is_my_blog --cov-fail-under 48 --cov-branch \
		--cov-report=term:skip-covered --timeout=30 --session-timeout=600

pytest: test-backend
	@echo "Running backend tests..."

# Run the mastodon_mock-backed integration tests (no live API keys needed).
# These boot the unpublished sibling mastodon_mock package as a local HTTP
# server and run the blog's Mastodon client against it. Kept out of the default
# `test` run because they require Python >=3.13 + the mastodon_mock dev dep, and
# need a longer per-test timeout than the unit suite (they spin up a server).
test-integration:
	@echo "Running mastodon_mock integration tests..."
	uv run python -m pytest test_integration -q --tb=short --timeout=30

# Run frontend unit tests (hermetic — mocked HTTP, no backend needed).
# Integration specs (src/**/*.integration.spec.ts) are excluded here.
test-frontend:
	@echo "Running frontend unit tests..."
	cd web && ng test --watch=false

# Run frontend integration tests against a LIVE backend (make dev-backend first).
# These hit real HTTP endpoints (read-only) and auto-skip if the server at
# http://localhost:8000 (override with MIMB_API_BASE) is unreachable.
test-frontend-integration:
	@echo "Running frontend integration tests (needs a running backend)..."
	cd web && npm run test:integration

# Lint code
lint: lint-backend lint-frontend

lint-check: lint

lint-backend:
	@echo "Linting Python code..."
	$(UV) run ruff check mastodon_is_my_blog test

lint-frontend:
	@echo "Linting TypeScript code..."
	cd web && ng lint

lint-frontend-strict:
	@echo "Linting TypeScript code (zero warnings)..."
	cd web && ng lint --max-warnings 0

audit-backend:
	@echo "Auditing Python dependencies..."
	uv run python -m pip_audit
	uv audit

security: audit-backend
	cd web && npm audit --audit-level=high

typecheck:
	@echo "Type-checking Python code..."
	$(UV) run python -m mypy mastodon_is_my_blog --ignore-missing-imports --check-untyped-defs

check: format-check lint-check typecheck security test build
	@echo "✓ Full quality gate passed"

check-ci: check

prerelease: prerelease-backend prerelease-frontend build-wheel
	@echo "✓ Prerelease checks passed"

prerelease-backend:
	@echo "Running backend prerelease checks..."
	uv run ruff check mastodon_is_my_blog/
	uv run python -m mypy mastodon_is_my_blog/
	uv run python -m pytest test -q --tb=line --no-header --color=no --cov=mastodon_is_my_blog --cov-fail-under 48 --cov-branch --cov-report=term:skip-covered --timeout=30 --session-timeout=600

prerelease-frontend:
	@echo "Running frontend prerelease checks..."
	cd web && npm run lint && npm run build && npm run test:ci

# Format code
format: format-backend format-frontend

format-backend:
	@echo "Formatting Python code..."
	uv run ruff format mastodon_is_my_blog/ test/
	uv run ruff check --fix mastodon_is_my_blog/ test/

format-frontend:
	@echo "Formatting TypeScript code..."
	cd web && npx prettier --write "src/**/*.{ts,html,scss}"

format-check:
	$(UV) run ruff format --check mastodon_is_my_blog test
	cd web && npm run format:check

# Clean build artifacts
clean:
	@echo "nope"

# Development utilities
logs-backend:
	@echo "Showing backend logs (if running in background)..."
	tail -f backend.log

logs-frontend:
	@echo "Showing frontend logs (if running in background)..."
	tail -f frontend.log

# Quick restart
restart: kill dev

kill:
	@echo "Stopping any running servers..."
	-pkill -f "uvicorn mastodon_is_my_blog.main:app"
	-pkill -f "ng serve"
	@echo "✓ Servers stopped"

# Check environment
check-env:
	@echo "Checking environment..."
	@command -v node >/dev/null 2>&1 || (echo "❌ Node.js not found"; exit 1)
	@command -v npm >/dev/null 2>&1 || (echo "❌ npm not found"; exit 1)
	@python3 --version
	@node --version
	@npm --version
	@echo "✓ Environment looks good"

# Update dependencies
update: update-backend update-frontend

update-backend:
	@echo "Updating Python dependencies..."
	uv sync --all-extras

update-frontend:
	@echo "Updating Node dependencies..."
	cd web && npm update

.PHONY:
mypy:
	@echo "Running mypy"
	uv run python -m mypy mastodon_is_my_blog --ignore-missing-imports --check-untyped-defs

.PHONY:
pylint:
	@echo "Running pylint"
	uv run pylint mastodon_is_my_blog --fail-under 9.9

.PHONY:
metadata:
	uv run metametameta pep621 --name mastodon_is_my_blog --source pyproject.toml
# ── Dogfooding targets (independent, not wired into check) ───────────────────

.PHONY: version-check
version-check:
	@uv run jiggle_version check

.PHONY: dev-status
dev-status:
	@uv run troml-dev-status validate .

.PHONY: prerelease-check
prerelease-check: version-check dev-status
	@echo "Pre-release checks passed."

.PHONY: dont-be-lazy
dont-be-lazy:
	@uv run dont_be_lazy --root . --no-color summary
	@uv run dont_be_lazy --root . --no-color scan mastodon_is_my_blog --no-config-suppressions || true

.PHONY: pydoc-docs
pydoc-docs:
	@uv run pydoc_fork mastodon_is_my_blog -o ./pydoc/

# ---------------------------------------------------------------------------
# Performance baselines — see rtd/reference/ensuring_mimb_stays_fast.md
#
# Big-DB benchmarks run locally only, at release time (not every build):
#   make perf-seed              (once per machine, ~1 GB sqlite db in perf/)
#   make perf-baseline-sqlite   (save the reference numbers)
#   make perf-check-sqlite      (fail on big regressions vs the saved baseline)
# Postgres variants seed/benchmark $(PERF_POSTGRES_URL) instead.
# perf-smoke is the short mastodon_mock-based check that also runs in CI.

PERF_DB ?= perf/mimb_perf.db
PERF_TARGET_MB ?= 1000
PERF_POSTGRES_URL ?= postgresql://postgres:xyzzy@localhost:5432/mimb_perf
# Only fail on big regressions; 40% on the median is far outside run-to-run noise.
PERF_FAIL_THRESHOLD ?= median:40%
PERF_PYTEST = $(UV) run python -m pytest test_perf/test_perf_sqlalchemy.py test_perf/test_perf_duckdb.py -q -p no:randomly --benchmark-storage=file://./.benchmarks

.PHONY: perf-seed perf-seed-postgres perf-baseline-sqlite perf-check-sqlite perf-baseline-postgres perf-check-postgres perf-smoke

perf-seed:
	@mkdir -p perf
	DB_URL=sqlite+aiosqlite:///$(PERF_DB) $(UV) run python -m test_perf.seed_perf_db --target-mb $(PERF_TARGET_MB)

perf-seed-postgres:
	DB_URL= DB_BACKEND=postgres APP_POSTGRES_URL=$(PERF_POSTGRES_URL) $(UV) run python -m test_perf.seed_perf_db --target-mb $(PERF_TARGET_MB)

perf-baseline-sqlite:
	MIMB_PERF=1 DB_URL=sqlite+aiosqlite:///$(PERF_DB) $(PERF_PYTEST) --benchmark-save=sqlite-baseline

perf-check-sqlite:
	MIMB_PERF=1 DB_URL=sqlite+aiosqlite:///$(PERF_DB) $(PERF_PYTEST) --benchmark-compare='*sqlite-baseline' --benchmark-compare-fail=$(PERF_FAIL_THRESHOLD)

perf-baseline-postgres:
	MIMB_PERF=1 DB_URL= DB_BACKEND=postgres APP_POSTGRES_URL=$(PERF_POSTGRES_URL) $(PERF_PYTEST) --benchmark-save=postgres-baseline

perf-check-postgres:
	MIMB_PERF=1 DB_URL= DB_BACKEND=postgres APP_POSTGRES_URL=$(PERF_POSTGRES_URL) $(PERF_PYTEST) --benchmark-compare='*postgres-baseline' --benchmark-compare-fail=$(PERF_FAIL_THRESHOLD)

perf-smoke:
	$(UV) run python -m pytest test_perf/test_perf_mock_smoke.py -q -p no:randomly --timeout=120
