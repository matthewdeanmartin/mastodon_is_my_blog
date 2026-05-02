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

.PHONY: help install install-backend install-frontend install-blog build-blog serve-blog dev dev-backend dev-frontend build build-wheel build-wheel-skip-ng publish publish-test install-from-wheel test test-backend test-frontend lint lint-backend lint-frontend lint-frontend-strict audit-backend prerelease prerelease-backend prerelease-frontend clean setup db-reset

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
	@echo "  make dev                - Run both backend and frontend (in parallel)"
	@echo "  make dev-backend        - Run FastAPI development server"
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
	@echo "  make test               - Run all tests"
	@echo "  make test-backend       - Run backend tests"
	@echo "  make test-frontend      - Run frontend tests"
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
	pip install -e .
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

# Run both servers (requires GNU parallel or similar)
dev:
	@echo "Starting backend and frontend servers..."
	@echo "Backend: http://localhost:8000"
	@echo "Frontend: http://localhost:4200"
	@echo ""
	@command -v parallel >/dev/null 2>&1 && \
		parallel ::: "make dev-backend" "make dev-frontend" || \
		(echo "Note: Install 'parallel' for better output, or run servers separately:"; \
		 echo "  Terminal 1: make dev-backend"; \
		 echo "  Terminal 2: make dev-frontend"; \
		 echo ""; \
		 echo "Starting backend only..."; \
		 make dev-backend)

# Run backend development server
dev-backend:
	@echo "Starting FastAPI server on http://localhost:8000"
	uvicorn mastodon_is_my_blog.main:app --reload --host 0.0.0.0 --port 8000

# Run frontend development server
dev-frontend:
	@echo "Starting Angular dev server on http://localhost:4200"
	cd web && ng serve --port 4200 --open

# Build Angular frontend for production only (no Python wheel)
build:
	@echo "Building Angular frontend for production..."
	cd web && ng build --configuration production
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
	uv run pytest test -q --tb=line --no-header --color=no --cov=mastodon_is_my_blog --cov-fail-under 48 --cov-branch --cov-report=term:skip-covered --timeout=5 --session-timeout=600 2>&1 | tail -50

pytest: test-backend
	@echo "Running backend tests..."


# Run frontend tests
test-frontend:
	@echo "Running frontend tests..."
	cd web && ng test --watch=false

# Lint code
lint: lint-backend lint-frontend

lint-backend:
	@echo "Linting Python code..."
	-ruff check mastodon_is_my_blog/
	-mypy mastodon_is_my_blog/

lint-frontend:
	@echo "Linting TypeScript code..."
	cd web && ng lint

lint-frontend-strict:
	@echo "Linting TypeScript code (zero warnings)..."
	cd web && ng lint --max-warnings 0

audit-backend:
	@echo "Auditing Python dependencies..."
	uv run pip-audit
	uv audit

prerelease: prerelease-backend prerelease-frontend build-wheel
	@echo "✓ Prerelease checks passed"

prerelease-backend:
	@echo "Running backend prerelease checks..."
	uv run ruff check mastodon_is_my_blog/
	uv run mypy mastodon_is_my_blog/
	uv run pytest test -q --tb=line --no-header --color=no --cov=mastodon_is_my_blog --cov-fail-under 48 --cov-branch --cov-report=term:skip-covered --timeout=5 --session-timeout=600

prerelease-frontend:
	@echo "Running frontend prerelease checks..."
	cd web && npm run lint && npm run build && npm run test:ci

# Format code
format: format-backend format-frontend

format-backend:
	@echo "Formatting Python code..."
	uv run ruff format mastodon_is_my_blog/

format-frontend:
	@echo "Formatting TypeScript code..."
	cd web && npx prettier --write "src/**/*.{ts,html,scss}"

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
	uv run mypy mastodon_is_my_blog --ignore-missing-imports --check-untyped-defs

.PHONY:
pylint:
	@echo "Running pylint"
	uv run pylint mastodon_is_my_blog --fail-under 9.9

.PHONY:
metadata:
	uv run metametameta pep621 --name mastodon_is_my_blog --source pyproject.toml