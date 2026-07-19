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
just dev       # backend (uvicorn :8025) + frontend (vite :5173)
just test      # pytest + vitest
just lint      # ruff + oxlint
```

Requires [just](https://github.com/casey/just), [uv](https://docs.astral.sh/uv/), and Node 22+
for local development; only Docker for `just up`.

## Status

Phase 1 (scaffold) — project layout, health check, dashboard shell, Docker image, and test
harnesses. The Twilio-compatible endpoints land in subsequent phases per
[SPEC.md §12](SPEC.md#12-build-phases).
