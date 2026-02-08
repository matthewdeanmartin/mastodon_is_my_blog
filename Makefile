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

.PHONY: help install install-backend install-frontend dev dev-backend dev-frontend build test clean setup db-reset

# Default target
help:
	@echo "Mastodon is My Blog - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make setup              - First-time setup (install dependencies + create .env)"
	@echo "  make install            - Install all dependencies (backend + frontend)"
	@echo "  make install-backend    - Install Python dependencies"
	@echo "  make install-frontend   - Install Node dependencies"
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
	@echo ""
	@echo "Testing:"
	@echo "  make test               - Run all tests"
	@echo "  make test-backend       - Run backend tests"
	@echo "  make test-frontend      - Run frontend tests"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean              - Remove build artifacts and caches"

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

# Build frontend for production
build:
	@echo "Building frontend for production..."
	cd web && ng build --configuration production
	@echo "✓ Build complete: web/dist/"

# Run all tests
test: test-backend test-frontend

# Run backend tests
test-backend:
	@echo "Running backend tests..."
	pytest

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

# Format code
format: format-backend format-frontend

format-backend:
	@echo "Formatting Python code..."
	-ruff format mastodon_is_my_blog/

format-frontend:
	@echo "Formatting TypeScript code..."
	cd web && npx prettier --write "src/**/*.{ts,html,scss}"

# Reset database
db-reset:
	@echo "Resetting database..."
	rm -f app.db
	@echo "✓ Database deleted. It will be recreated on next backend start."

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts and caches..."
	rm -rf web/dist/
	rm -rf web/.angular/
	rm -rf web/node_modules/.cache/
	rm -rf **/__pycache__/
	rm -rf **/*.pyc
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf *.egg-info/
	@echo "✓ Cleaned"

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
	@command -v python3 >/dev/null 2>&1 || (echo "❌ Python 3 not found"; exit 1)
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
	pip install --upgrade -e .

update-frontend:
	@echo "Updating Node dependencies..."
	cd web && npm update

# Generate static site (future feature)
generate-static:
	@echo "Generating static site..."
	@echo "⚠️  This feature is not yet implemented"
	@echo "TODO: Add static site generation"