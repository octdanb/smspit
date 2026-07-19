# Configuration

smspit is configured in two layers:

- **Environment variables** — where it runs: port, database, dashboard auth. Set on the
  container.
- **Settings** — how it behaves: webhooks, delivery simulation, strict mode, and so on. Stored
  in the database, edited on the dashboard's Settings page or via
  `PUT /api/settings` with a JSON body (send only the keys you want to change).

## Environment variables

These are all the variables the Docker image reads:

| Variable | Default | Purpose |
|---|---|---|
| `SMSPIT_PORT` | `8025` | Port the server listens on. The published image already exposes and binds 8025, so with Docker you'd normally remap with `-p` instead of changing this. |
| `SMSPIT_DB_PATH` | `./data/smspit.db` (image: `/data/smspit.db`) | SQLite database file. Mount its directory as a volume to keep messages across restarts. |
| `SMSPIT_STATIC_DIR` | `./static` (image: `/app/static`) | Directory containing the built dashboard. Baked into the image — only relevant when running from source. |
| `SMSPIT_DASHBOARD_TOKEN` | *(unset — no auth)* | When set, the dashboard and the internal `/api` require this token: send an `X-Smspit-Token` header, or open `http://host:8025/?token=…` once and the dashboard remembers it. Twilio-shaped routes and `/api/health` are never gated, so the app under test and health probes keep working. |

Example:

```sh
docker run -p 8025:8025 \
  -v ./data:/data \
  -e SMSPIT_DASHBOARD_TOKEN=change-me \
  ghcr.io/octdanb/octavenz-smspit:latest
```

Everything else below lives in settings, not the environment — it can be changed at runtime
without a restart.

## Settings reference

Fields documented as JSON take a JSON value (the dashboard's Settings page edits them as text).
Unlisted keys sent to `PUT /api/settings` are rejected, so typos fail loudly.

### Identity & inbound webhook

| Setting | Default | Purpose |
|---|---|---|
| `account_sid` | `AC000…000` | Account SID echoed into resources and used for webhook signatures. |
| `auth_token` | `smspit-auth-token` | Token used to compute `X-Twilio-Signature` on outgoing webhooks (and checked by `strict_auth`). Point your app's Twilio auth token at the same value so its `RequestValidator` passes. |
| `inbound_webhook_url` | `null` | Where simulated replies are delivered as Twilio-format webhooks. Per-number (`IncomingPhoneNumbers`) and per-Messaging-Service URLs take precedence when configured. |
| `inbound_webhook_method` | `POST` | `POST` (form-encoded) or `GET` (query params, signed the way Twilio signs GETs). |
| `public_base_url` | `http://localhost:8025` | Base URL used when building media links inside webhooks. Set to the public URL on shared instances so your app can actually fetch the media. |
| `webhook_geo_params` | `{}` | JSON object of geo fields merged into inbound webhooks (`FromCity`, `FromCountry`, …). |

### Delivery simulation

| Setting | Default | Purpose |
|---|---|---|
| `simulate_delivery` | `true` | Walk each sent message through `queued → sending → sent → delivered`, firing status callbacks along the way. Off = messages stay `queued`. |
| `status_delay_ms` | `300` | Delay between status transitions. |
| `failure_rate` | `0.0` | Chance (0–1) that a message ends `undelivered` instead of `delivered`. |
| `forced_rules` | `[]` | Deterministic failures for tests: JSON list of `{"to_suffix": "0000", "status": "undelivered", "error_code": 30007}`. Matching sends always get that outcome. |

### Strict mode

Everything defaults to permissive — any credentials, any numbers. Turn checks on individually
to test your error handling. See [twilio-compatibility.md](twilio-compatibility.md) for the
exact error codes each check raises.

| Setting | Default | Purpose |
|---|---|---|
| `strict_auth` | `false` | Basic-auth credentials must match `account_sid`/`auth_token` (or the API key pair below). |
| `api_key_sid` / `api_key_secret` | empty | Optional `SK…` API key pair also accepted by `strict_auth`. |
| `strict_validation` | `false` | Validate To/From numbers, landline checks (per Lookup overrides), WhatsApp session window. |
| `enforce_optouts` | `false` | Reject sends to opted-out recipients. |
| `trial_mode` | `false` | Only allow sends to `verified_numbers`, like a Twilio trial account. |
| `verified_numbers` | `[]` | JSON list of E.164 numbers allowed in trial mode. |
| `rate_limit_per_minute` | `0` | When non-zero, sends past the limit get `429`. |

### Opt-outs

| Setting | Default | Purpose |
|---|---|---|
| `optout_config` | Twilio's defaults | JSON: `{"keywords": {"stop": […], "start": […], "help": […]}, "confirmations": {"stop": "…", "start": "…", "help": "…"}}`. Customize keyword lists and the auto-reply bodies. |

### Verify & Lookup

| Setting | Default | Purpose |
|---|---|---|
| `verify_ttl_seconds` | `600` | How long Verify v2 codes stay valid. |
| `lookup_line_types` | `{}` | JSON map of E.164 → line type (`"landline"`, `"nonFixedVoip"`, …) returned by Lookup's `line_type_intelligence` and used by strict validation's landline check. Everything else reports `mobile`. |

### Tags & retention

| Setting | Default | Purpose |
|---|---|---|
| `auto_tag_rules` | `[]` | JSON list of `{"tag": "otp", "body_regex": "code is \\d+"}` (also `to_suffix` / `from_suffix`) applied to every captured message. |
| `retention_max_age_hours` | `0` (keep forever) | Auto-purge messages older than this. |
| `retention_max_messages` | `0` (unlimited) | Keep at most this many messages. |

### Webhook chaos

For testing your app's webhook resilience:

| Setting | Default | Purpose |
|---|---|---|
| `webhook_latency_ms` | `0` | Artificial delay before every webhook delivery. |
| `webhook_failure_rate` | `0.0` | Chance (0–1) a delivery is dropped (logged as an error). |
| `webhook_retry_count` | `0` | Retries (with backoff) after a failed delivery; every attempt is logged. |

### Release to real Twilio

Forward captured messages through real Twilio — smspit's version of Mailpit's SMTP relay. The
allowlist is mandatory: a release to a number not on it is refused, so the mock can never text
real people by accident.

| Setting | Default | Purpose |
|---|---|---|
| `real_account_sid` / `real_auth_token` | empty | Real Twilio credentials used for releases. |
| `real_from_number` | empty | The real Twilio number releases are sent from. |
| `release_allowlist` | `[]` | JSON list of E.164 numbers releases may target. |
| `auto_forward_to` | empty | Forward every captured outbound message to this (allowlisted) number automatically. |

### Capture webhook

| Setting | Default | Purpose |
|---|---|---|
| `capture_webhook_url` | empty | Gets a fire-and-forget JSON POST for every captured message — point CI or a Slack bridge at it. |
