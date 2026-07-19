# smspit workflows

default:
    @just --list

# Run backend (uvicorn --reload) + frontend (vite dev) behind Caddy on :8025
dev:
    #!/usr/bin/env bash
    set -euo pipefail
    trap 'kill 0' EXIT
    (cd backend && uv run uvicorn app.main:app --reload --port 8825) &
    (cd frontend && pnpm run dev) &
    caddy run --config Caddyfile --adapter caddyfile &
    wait

# Run unit tests (pytest + vitest)
test:
    cd backend && uv run pytest
    cd frontend && pnpm test

# Run the real-SDK conformance suites against a live instance (starts one for you)
conformance:
    #!/usr/bin/env bash
    set -euo pipefail
    (cd backend && uv run uvicorn app.main:app --port 8025) &
    server=$!
    trap 'kill $server' EXIT
    for i in $(seq 1 30); do curl -sf localhost:8025/api/health && break; sleep 1; done
    uv run --project conformance/python pytest conformance/python -v
    cd conformance/node && pnpm install && pnpm test

# Build the dashboard and run the Playwright E2E suite against it
e2e:
    #!/usr/bin/env bash
    set -euo pipefail
    (cd frontend && pnpm install && pnpm run build)
    (cd backend && SMSPIT_STATIC_DIR=../frontend/dist uv run uvicorn app.main:app --port 8025) &
    server=$!
    trap 'kill $server' EXIT
    for i in $(seq 1 30); do curl -sf localhost:8025/api/health && break; sleep 1; done
    cd e2e && pnpm install && pnpm exec playwright test

# Load demo fixtures into a running instance (for screenshots / a quick look)
seed url="http://localhost:8025":
    curl -fsS -X POST {{url}}/api/seed && echo

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
    cd frontend && pnpm run lint

fmt:
    cd backend && uv run ruff format .
    cd frontend && pnpm run fmt
