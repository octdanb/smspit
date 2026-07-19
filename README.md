# smspit

**Mailpit, but for SMS.** A local Twilio-emulating SMS testing tool for developers.

Point your app's Twilio base URL at smspit during development: every message is captured and
shown in a web dashboard, you can simulate replies (delivered to your app as Twilio-format
webhooks), and E2E tests can fetch the latest OTP code for any number. In production, switch
back to real Twilio by changing one environment variable — no code changes.

Emulates Twilio's **Programmable Messaging (2010-04-01)**, **Verify v2**, **Messaging Services
v1**, and **Lookup v2** APIs. See [SPEC.md](SPEC.md) for the full emulation contract and build
plan.

## Quickstart

```sh
just up        # docker compose — dashboard + API on http://localhost:8025
```

Development:

```sh
just dev       # everything on http://localhost:8025 (Caddy → uvicorn :8825 + vite :5173)
just test      # pytest + vitest
just lint      # ruff + oxlint
```

`just dev` fronts the API and the Vite dev server (with HMR) through
[Caddy](https://caddyserver.com/) on a single port, so dev looks exactly like the production
container: everything on `http://localhost:8025`. Hitting the Vite server directly on `:5173`
also works (it proxies API paths to the backend).

Requires [just](https://github.com/casey/just), [uv](https://docs.astral.sh/uv/), Node 22+, and
[caddy](https://caddyserver.com/docs/install) (`apt install caddy` / `brew install caddy`) for
local development; only Docker for `just up`.

## Status

Phases 1–4 complete: message capture (send/list/fetch with Twilio-shaped resources, pagination,
segment math), live dashboard updates over WebSocket, delivery lifecycle simulation
(queued → sending → sent → delivered, configurable delays/failures), status callbacks signed
with X-Twilio-Signature, webhook delivery log with retry, message update (redact/cancel) and
delete, and scheduled sends. Next per [SPEC.md §12](SPEC.md#12-build-phases): two-way messaging
(replies + inbound webhooks + TwiML), verification/OTP support, Messaging Services, Lookup.
