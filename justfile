# smspit workflows

default:
    @just --list

# Run backend (uvicorn --reload) + frontend (vite dev) behind Caddy on :8025
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    (cd backend && uv run uvicorn app.main:app --reload --port 8825) &
    (cd frontend && npm run dev) &
    caddy run --config Caddyfile --adapter caddyfile &
    wait

# Run all tests (pytest + vitest)
test:
    cd backend && uv run pytest
    cd frontend && npm test

# Build the Docker image
build:
    docker build -t smspit .

# Start / stop via docker compose
up:
    docker compose up --build -d

down:
    docker compose down

# Lint (ruff + oxlint) and format (ruff + prettier)
lint:
    cd backend && uv run ruff check .
    cd frontend && npm run lint

fmt:
    cd backend && uv run ruff format .
    cd frontend && npm run fmt
