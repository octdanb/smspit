# smspit

**Mailpit, but for SMS.** A local Twilio-emulating SMS testing tool for developers.

Point your app's Twilio base URL at smspit during development: every message is captured and
shown in a live web dashboard, you can simulate replies (delivered to your app as signed
Twilio-format webhooks, with TwiML auto-reply support), and E2E tests can fetch the latest OTP
code for any number. In production, switch back to real Twilio by changing one environment
variable — no code changes.

**Emulated Twilio surfaces** (see [SPEC.md](SPEC.md) for the full contract):

| API | What works |
|---|---|
| Programmable Messaging (2010-04-01) | send/list/fetch/update/delete, Twilio-shaped resources + pagination, MMS media subresource, scheduled sends + cancel, redaction, delivery lifecycle (`queued → sending → sent → delivered`) with status callbacks, GSM-7/UCS-2 segment math, opt-out keywords (STOP/START/HELP) |
| Messaging Services (v1) | service CRUD, sender pools (numbers / alpha senders / short codes), `accepted` flow with sticky sender + area-code geomatch, service-level callbacks and inbound routing |
| Verify (v2) | services, verifications, checks — attempt limits, expiry, custom codes; codes arrive as real messages |
| Lookup (v2) | validation via `phonenumbers`, `line_type_intelligence` with per-number overrides |

All webhooks (inbound messages + status callbacks) are signed with a real `X-Twilio-Signature`,
so Twilio's `RequestValidator` middleware passes unchanged.

## Quickstart

```sh
just up        # docker compose — dashboard + API on http://localhost:8025
```

or grab the published image:

```sh
docker run -p 8025:8025 -v ./data:/data ghcr.io/octdanb/octavenz-smspit:latest
```

## Pointing your app at smspit

Everything is served on one port, routed by path (`/2010-04-01`, `/v1`, `/v2`), so raw-HTTP
integrations need a single base URL:

```sh
TWILIO_API_BASE_URL=http://localhost:8025   # dev
# unset in production → https://api.twilio.com
```

Official SDKs pin per-product hosts; override each sub-client you use:

```python
# Python (twilio-python)
import os
from twilio.rest import Client

client = Client(account_sid, auth_token)
if base := os.environ.get("TWILIO_API_BASE_URL"):
    client.api.base_url = base       # Programmable Messaging
    client.messaging.base_url = base # Messaging Services
    client.verify.base_url = base    # Verify
    client.lookups.base_url = base   # Lookup

client.messages.create(to="+64211234567", from_="+6421000000", body="Your code is 123456")
```

```ts
// Node (twilio)
import twilio from "twilio";

const client = twilio(accountSid, authToken);
const base = process.env.TWILIO_API_BASE_URL;
if (base) {
  for (const product of ["api", "messaging", "verify", "lookups"] as const) {
    (client[product] as any).baseUrl = base;
  }
}

await client.messages.create({ to: "+64211234567", from: "+6421000000", body: "Your code is 123456" });
```

Any HTTP client works too — the API is form-encoded exactly like Twilio's:

```sh
curl -u $TWILIO_ACCOUNT_SID:$TWILIO_AUTH_TOKEN \
  --data-urlencode "To=+64211234567" \
  --data-urlencode "From=+6421000000" \
  --data-urlencode "Body=Hello from smspit" \
  http://localhost:8025/2010-04-01/Accounts/$TWILIO_ACCOUNT_SID/Messages.json
```

### Receiving replies

Set your app's inbound webhook URL on the Settings page (or
`PUT /api/settings {"inbound_webhook_url": "http://localhost:3000/sms"}`). Replies typed in the
dashboard arrive at your app as Twilio-format webhooks — including `X-Twilio-Signature` — and a
TwiML `<Response><Message>` reply is rendered back into the conversation.

## Testing OTP / verification flows

`GET /api/numbers/{number}/latest-code` returns the most recent 4–8 digit code sent to a number
(optionally `?regex=` with a capture group). Works for both plain SMS OTPs and Verify v2.

```python
# pytest
import httpx

def test_signup_otp(page):  # your app drives the SMS send
    page.goto("http://localhost:3000/signup")
    page.fill("#phone", "+64211234567")
    page.click("#send-code")

    code = httpx.get(
        "http://localhost:8025/api/numbers/+64211234567/latest-code"
    ).json()["code"]
    page.fill("#otp", code)
    page.click("#verify")
```

```ts
// Playwright
const response = await request.get(
  "http://localhost:8025/api/numbers/+64211234567/latest-code",
);
const { code } = await response.json();
await page.getByLabel("Verification code").fill(code);
```

Deterministic failure testing: `PUT /api/settings` with
`{"forced_rules": [{"to_suffix": "0000", "status": "undelivered", "error_code": 30007}]}` makes
every send to a number ending `0000` fail with error 30007 — status callbacks included.

**Fixtures**: `POST /api/seed` loads demo conversations (or pass
`{"messages": [{from_number, to_number, body, direction?, tags?}]}` for custom fixtures) —
handy for screenshots and demo environments.

**Webhook chaos** (settings): `webhook_latency_ms` delays every delivery,
`webhook_failure_rate` drops a fraction of them, and `webhook_retry_count` retries failed
deliveries with backoff (each attempt logged) — for testing your app's webhook resilience.

## Strict mode

Permissive by default (any credentials, any numbers). Opt into Twilio-grade behavior per check
on the Settings page or via `PUT /api/settings`:

| Setting | Effect |
|---|---|
| `strict_auth` | wrong SID/token → 401 / `20003` (API key pair accepted via `api_key_sid`/`api_key_secret`) |
| `strict_validation` | malformed To → `21211`, bad From → `21212`, landline (per Lookup overrides) → `21614`, WhatsApp free-form outside the 24h session window → `63016` |
| `enforce_optouts` | sends to STOPped numbers → `21610` |
| `trial_mode` + `verified_numbers` | sends to unverified numbers → `21608` |
| `rate_limit_per_minute` | over the limit → 429 / `20429` |

## Development

```sh
just dev       # everything on http://localhost:8025 (Caddy → uvicorn :8825 + vite :5173)
just test      # pytest + vitest
just lint      # ruff + oxlint
```

`just dev` fronts the API and the Vite dev server (with HMR) through
[Caddy](https://caddyserver.com/) on a single port, so dev looks exactly like the production
container. Hitting the Vite server directly on `:5173` also works.

Requires [just](https://github.com/casey/just), [uv](https://docs.astral.sh/uv/), Node 22+, and
[caddy](https://caddyserver.com/docs/install) (`apt install caddy` / `brew install caddy`) for
local development; only Docker for `just up`.

## CI & Releases

GitHub Actions ([ci.yml](.github/workflows/ci.yml)) runs on every PR:

- backend: ruff, pytest, and a `pip-audit` dependency audit
- frontend: oxlint, prettier check, vitest, build, and `npm audit` (high severity fails)
- **SDK conformance**: the real `twilio-python` and `twilio-node` SDKs run against a live
  instance ([conformance/](conformance/)) — send, pagination, media, Verify, Messaging
  Services, Lookup, error codes
- **Dashboard E2E**: a Playwright suite ([e2e/](e2e/)) drives the built dashboard — live
  updates, replies + TwiML auto-replies, OTP chips, tag filtering, the detail drawer

Then the Docker image builds (multi-arch `linux/amd64` + `linux/arm64` on pushes). On `main`
the image is published to GHCR as `ghcr.io/<owner>/octavenz-smspit:latest` (+ a `sha-…` tag).

Releases are semver git tags: pushing `v1.2.3` publishes the image tagged `1.2.3`, `1.2`, and
`1` (the workflow also tolerates `V1.2.3` and bare `1.2.3`, but lowercase `v` is the
convention):

```sh
git tag v0.2.0 && git push origin v0.2.0
```

## Dashboard workflow features

- **Tags** (Mailpit-style): tag messages manually in the detail drawer, define auto-tag rules
  in settings (`[{"tag": "otp", "body_regex": "code is \\d+"}]`, also `to_suffix`/`from_suffix`),
  or send with Twilio's `Tags` parameter — they surface as `key:value` tags. Filter the sidebar
  with `tag:` in search or by clicking a chip; `GET /api/tags` lists them for automation.
- **Unread indicators** per thread; opening a thread marks it read.
- **Message detail drawer** (click any bubble): full Twilio-shaped JSON, the original request
  params, tag editing, copy SID, delete.
- **Scheduled view** with cancel, **webhook log filters** (kind / result / message SID),
  **export** (thread or everything, JSON/CSV), and **retention** (auto-purge by age or count).
- **Optional dashboard auth**: set `SMSPIT_DASHBOARD_TOKEN` and the internal API + dashboard
  require it (`X-Smspit-Token` header, or open `http://localhost:8025/?token=…` once); Twilio
  routes and `/api/health` are unaffected.
- **Release to real Twilio** (Mailpit's relay analog): configure real credentials + a recipient
  **allowlist** in settings, then release any captured message from the detail drawer or
  `POST /api/messages/{sid}/release` — or auto-forward everything to a tester's phone. Nothing
  is ever sent to a number that isn't explicitly allowlisted.
- **Search operators**: `tag:` `from:` `to:` `status:` `has:media` `is:unread`
  `before:`/`after:YYYY-MM-DD`, combinable with free text.
- **Capture webhook**: `capture_webhook_url` gets a JSON POST for every captured message
  (fire-and-forget) — point CI or a Slack bridge at it.
- **Desktop notifications** (bell toggle) when new messages arrive while the tab is hidden, and
  an **encoding check** in the detail drawer showing exactly which characters force UCS-2 and
  what Smart Encoding would save.

## Roadmap

All 12 phases of [SPEC.md §12](SPEC.md#12-build-phases) are shipped, including the Mailpit
feature-parity pass (release/forwarding, search operators, capture webhook, notifications,
encoding check).

## Non-goals

No real SMS delivery, no dashboard auth (local dev tool), single-tenant. Out of scope: voice,
email, RCS, WhatsApp template approval flows, Lookup data packages beyond
`line_type_intelligence`.
