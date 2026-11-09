# Run from the repo root. Needs uv (Python 3.12) and Node 22 (see frontend/.nvmrc).

.PHONY: install dev backend frontend test lint sample eval check

install:
	cd backend && uv sync
	cd frontend && npm ci

# Backend on 8040 and the app on 3040.
dev:
	@echo "API on http://localhost:8040 (docs at /docs), app on http://localhost:3040"
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --port 8040) & \
	(cd frontend && npm run dev) & \
	wait

backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8040

frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run lint && npm run typecheck

# Regenerate the sample documents and their ground truth.
sample:
	cd backend && uv run python sample/generate.py

# Score a provider against the ground truth: make eval PROVIDER=anthropic
PROVIDER ?= mock
eval:
	cd backend && uv run python -m app.evals --provider=$(PROVIDER)

check: lint test eval
	cd frontend && npm run build
