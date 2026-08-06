# Contributing to smspit

Thanks for your interest! smspit is a Twilio-emulating SMS testing tool
("Mailpit, but for SMS"). This guide covers local setup and the checks CI runs.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python 3.11+)
- Node 22+ with [pnpm](https://pnpm.io/) 10 — run `corepack enable` to pick up
  the pinned version automatically (on Node 25+, which no longer bundles it,
  `npm install -g corepack` first)
- [just](https://github.com/casey/just) for the task runner
- [caddy](https://caddyserver.com/docs/install) for `just dev`
- Docker for `just up` / `just build`

## Getting started

```sh
just dev        # backend + dashboard on http://localhost:8025 (one port, HMR)
just seed       # optional: load demo conversations
```

## Checks

Run these before opening a PR — CI runs the same:

```sh
just lint       # ruff + oxlint
just test       # pytest + vitest
just conformance  # real twilio-python / twilio-node SDKs against a live instance
just e2e        # Playwright suite against the built dashboard
```

Formatting: `just fmt` (ruff + prettier). CI checks formatting, so run it before
committing.

## Pull requests

- Keep changes focused; add tests for new behavior (backend uses pytest,
  frontend vitest, and the E2E suite for dashboard flows).
- Twilio-shaped behavior should match the real API — see
  [docs/twilio-compatibility.md](docs/twilio-compatibility.md) and, when in
  doubt, [twilio/twilio-oai](https://github.com/twilio/twilio-oai).
- New settings go on the `Settings` model; the additive migration in
  `backend/app/db.py` handles upgrades against existing databases automatically.

## Reporting security issues

Please don't file public issues for security problems — see
[SECURITY.md](SECURITY.md).
