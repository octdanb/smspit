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

## CI & Releases

GitHub Actions ([ci.yml](.github/workflows/ci.yml)) runs ruff + pytest, oxlint + vitest + the
frontend build on every PR, then builds the Docker image. On pushes to `main` the image is
published to GHCR as `ghcr.io/<owner>/octavenz-smspit:latest` (+ a `sha-…` tag).

Releases are semver git tags: pushing `v1.2.3` publishes the image tagged `1.2.3`, `1.2`, and
`1`:

```sh
git tag v0.1.0 && git push origin v0.1.0
docker run -p 8025:8025 -v ./data:/data ghcr.io/<owner>/octavenz-smspit:0.1.0
```

## Status

Phases 1–5 complete: message capture (send/list/fetch with Twilio-shaped resources, pagination,
segment math), live dashboard updates over WebSocket, delivery lifecycle simulation
(queued → sending → sent → delivered, configurable delays/failures), status callbacks signed
with X-Twilio-Signature, webhook delivery log with retry, message update (redact/cancel) and
delete, scheduled sends, two-way messaging (inbound webhooks, TwiML auto-replies, the
STOP/START/HELP opt-out engine, MMS media), verification support (OTP extraction,
`latest-code`, Twilio Verify v2), Messaging Services v1 (sender pools with sticky sender and
area-code geomatch, the `accepted` status flow, service-level callbacks and inbound routing),
and Lookup v2 (real number parsing via `phonenumbers`, configurable line-type intelligence).
Remaining per [SPEC.md §12](SPEC.md#12-build-phases): phase 8 polish (full strict mode, dark
mode, SDK-switching docs).
