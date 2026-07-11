.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

.PHONY: help install format format-check lint test test-ci build build-web build-lite security dead-code check check-ci update

help:
	@echo "Angular quality gates (main UI + Lite):"
	@echo "  make install       Install locked dependencies"
	@echo "  make format        Auto-format sources"
	@echo "  make format-check  Check formatting without changes"
	@echo "  make lint          Lint TypeScript and templates"
	@echo "  make test          Test both clients with coverage"
	@echo "  make build         Production-build both clients"
	@echo "  make security      Audit production dependencies"
	@echo "  make check         Full read-only quality gate"

install:
	npm ci

format:
	npm run format

format-check:
	npm run format:check

lint:
	npm run lint

test:
	npm run test:ci

coverage:
	npm run test:ci

test-ci: test

build:
	npm run build:all

build-web:
	npm run build

build-lite:
	npm run build:lite

security:
	npm audit --omit=dev --audit-level=high

check: format-check lint test build security

check-ci: check

dead-code:
	npm run dead-code

update:
	npm install -g @angular/cli@latest
	ng update @angular/cli @angular/core
	npm dedupe
