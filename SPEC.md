# smspit — SMS Mock Service Specification

**Mailpit, but for SMS.** A local Twilio-emulating SMS testing tool for developers.

During development, applications send SMS through this service instead of Twilio. It captures
every message, displays them in a web dashboard, supports simulated replies, and exposes helpers
for automated testing of SMS verification flows. In production, the app switches to real Twilio
by changing only the API base URL — no code changes.

This document is the build contract: it specifies the complete Twilio-compatible surface the
service emulates, the internal API, the dashboard, the data model, and the phased build plan.
Exact field shapes were sourced from Twilio's official docs and their code-generated client
libraries; during implementation, [`twilio/twilio-oai`](https://github.com/twilio/twilio-oai)
(Twilio's OpenAPI specs) is the authoritative schema reference.

---

## Core Value Proposition

- **Twilio drop-in**: exposes Twilio-compatible REST APIs (Programmable Messaging, Verify,
  Messaging Services, Lookup) so switching between dev (this service) and prod (Twilio) is a
  single base-URL change.
- **Zero config**: single Docker container, SQLite storage, no external dependencies.
- **Two-way simulation**: reply to messages from the dashboard; the service delivers inbound
  messages to the app under test via Twilio-format webhooks, including TwiML auto-reply handling.
- **Test automation friendly**: API endpoints to fetch the latest OTP/verification code for a
  number, plus deterministic failure simulation, for Playwright/pytest E2E tests.
- **Configurable fidelity**: permissive by default (accept anything), with opt-in strict mode
  that validates like real Twilio and raises real Twilio error codes — so error-handling paths
  are testable too.

## Tech Stack

- **Backend**: Python, FastAPI, SQLModel, SQLite, WebSockets (uvicorn), httpx, phonenumbers
- **Frontend**: React + TypeScript, Vite, Tailwind CSS, shadcn/ui, TanStack Query, TanStack Router
- **Tooling**: Docker (single image, multi-stage build), docker-compose for dev, justfile for all workflows
- **Testing**: pytest (backend), vitest (frontend)

## Architecture

```
┌──────────────────┐   Twilio-compatible APIs   ┌─────────────────────────┐
│ App under test   │ ─────────────────────────▶ │  FastAPI backend        │
│                  │ ◀───────────────────────── │  - Messaging 2010-04-01 │
│ (inbound webhook,│   Twilio-format webhooks   │  - Verify v2            │
│  status callback)│   + X-Twilio-Signature     │  - Messaging Svcs v1    │
└──────────────────┘                            │  - Lookup v2            │
                                                │  - Internal REST API    │
                                                │  - WebSocket events     │
                                                │  - SQLite (SQLModel)    │
                                                └───────────┬─────────────┘
                                                            │ serves static build + API
                                                ┌───────────▼─────────────┐
                                                │ React dashboard (Vite)  │
                                                │ shadcn/ui + Tailwind    │
                                                │ TanStack Query + Router │
                                                └─────────────────────────┘
```

Single container: FastAPI serves both the APIs and the built React app on one port (default
**8025**). All Twilio API families are routed by path prefix (`/2010-04-01`, `/v1`, `/v2`), so a
single base-URL override covers everything.

---

## 1. Twilio-Compatible Surface — Programmable Messaging (2010-04-01)

### 1.1 Authentication

HTTP Basic on all Twilio-shaped routes. Username = AccountSid (`AC…`) or API Key SID (`SK…`);
password = auth token / key secret.

- **Permissive mode (default)**: any non-empty credentials accepted; the given AccountSid is
  echoed into resources.
- **Strict mode**: credentials must match the configured account SID + auth token → otherwise
  HTTP 401 with error code `20003` in the standard error envelope (§1.10).

### 1.2 Send a message

`POST /2010-04-01/Accounts/{AccountSid}/Messages.json` — `application/x-www-form-urlencoded`,
PascalCase parameters:

| Parameter | Type | Semantics |
|---|---|---|
| `To` | string | **Required.** E.164, short code, or channel address (`whatsapp:+…`). |
| `From` | string | E.164 / short code / alphanumeric sender / channel address. Required unless `MessagingServiceSid` given. |
| `MessagingServiceSid` | `MG…` | Send via a Messaging Service sender pool (§4). |
| `Body` | string ≤1600 chars | Message text. One of `Body`/`MediaUrl`/`ContentSid` required. |
| `MediaUrl` | URL, repeatable | MMS attachments. |
| `ContentSid` | `HX…` | Content template SID. Accepted; body rendered from `ContentVariables` as plain text. |
| `ContentVariables` | JSON string | Template substitutions. |
| `StatusCallback` | URL | Receives status webhooks (§2.3). |
| `ApplicationSid` | `AP…` | Accepted and stored. |
| `ValidityPeriod` | int 1–36000 (default 36000) | Max queue time in seconds. |
| `SmartEncoded` | bool | Substitute non-GSM look-alike chars to stay in GSM-7 (§1.7). |
| `ShortenUrls` | bool | Accepted; no-op recorded on the message. |
| `ScheduleType` | `fixed` | Scheduled send; requires `SendAt` + `MessagingServiceSid`. |
| `SendAt` | ISO 8601 | Send time; Twilio window is ~15 min–7 days ahead (validated in strict mode). |
| `SendAsMms` | bool | Force MMS (`MM…` SID) even without media. |
| `RiskCheck` | `enable`\|`disable` | Accepted and stored. |
| `ProvideFeedback` | bool | Enables the Feedback subresource (§1.6). |
| `Attempt` | int | Accepted and stored. |
| `ContentRetention` | `retain`\|`discard` | Accepted and stored. |
| `AddressRetention` | `retain`\|`obfuscate` | Accepted and stored. |
| `PersistentAction` | string, repeatable | Accepted and stored. |
| `MaxPrice` | decimal | Obsolete at Twilio (2024-06) — accepted, ignored. |
| `ForceDelivery` | bool | Reserved — accepted, ignored. |
| `Tags` | JSON string | Stored; echoed as `tags`. |

**Validation (strict mode)** raises real Twilio errors: `21211` invalid `To`, `21212`/`21606`
invalid `From`, `21602` no content, `21604` missing `To`, `21608` unverified `To` (trial-mode
toggle), `21610` opted-out recipient (§3), `21614` `To` not a mobile number (per Lookup
line-type overrides, §6), `21617` body over 1600 chars.

### 1.3 Message resource shape

JSON, snake_case. Fidelity details that matter to SDKs:

- `num_media`, `num_segments`, `price` are JSON **strings** (`"0"`, `"1"`, `"-0.00750"`).
- Dates (`date_created`, `date_updated`, `date_sent`) are **RFC 2822** GMT:
  `Fri, 24 May 2019 17:44:46 +0000`. `date_sent` is `null` until sent.
- `sid`: `SM` + 32 hex for SMS, `MM` + 32 hex for MMS.
- `direction`: `inbound` | `outbound-api` | `outbound-call` | `outbound-reply`.
- `price` simulated per segment (`-0.0075 × num_segments`), `price_unit: "USD"`, populated when
  the message reaches `sent`.
- `subresource_uris`: `{ "media": "…/Messages/{sid}/Media.json", "feedback": "…/Feedback.json" }`.
- Full field list: `sid`, `account_sid`, `api_version` (`2010-04-01`), `body`, `num_media`,
  `num_segments`, `direction`, `from`, `to`, `date_created`, `date_updated`, `date_sent`,
  `price`, `price_unit`, `error_code` (int|null), `error_message` (string|null), `status`,
  `messaging_service_sid`, `uri`, `subresource_uris`, `tags`.

### 1.4 Statuses & lifecycle simulation

All Twilio wire statuses are supported:
`accepted`, `scheduled`, `queued`, `sending`, `sent`, `delivered`, `undelivered`, `failed`,
`receiving`, `received`, `read`, `partially_delivered`, `canceled`.

Simulated lifecycle (configurable per-status delays, default a few hundred ms):

- Direct send: `queued → sending → sent → delivered`
- Via Messaging Service: `accepted → queued → …` (the pool-selected `from` appears at `queued`)
- Scheduled: `scheduled` until `SendAt` (or canceled), then the normal chain
- Failure simulation: global failure rate + **per-number forced outcomes** (deterministic rules,
  e.g. "`To` ending `0000` → `undelivered` with `error_code 30007`") so E2E tests can trigger
  failures reliably. Failure codes: `30003` unreachable, `30004` blocked, `30005` unknown handset,
  `30006` landline/unreachable carrier, `30007` filtered, `30008` unknown error.
- Inbound (simulated replies): recorded as `received`.

Each transition fires the status callback webhook (§2.3) and a WebSocket event (§7).

### 1.5 List / fetch / update / delete

**List** — `GET …/Messages.json`. Filters: `To`, `From`, `DateSent`, `DateSent<`, `DateSent>`
(dates `YYYY-MM-DD` or ISO 8601), `PageSize` (default 50, max 1000), `Page`, `PageToken`.
Twilio pagination envelope (record key is the resource name):

```json
{
  "messages": [ … ],
  "page": 0,
  "page_size": 50,
  "first_page_uri": "/2010-04-01/Accounts/AC…/Messages.json?PageSize=50&Page=0",
  "previous_page_uri": null,
  "next_page_uri": "/2010-04-01/Accounts/AC…/Messages.json?PageSize=50&Page=1&PageToken=PA…",
  "uri": "/2010-04-01/Accounts/AC…/Messages.json?PageSize=50&Page=0",
  "start": 0,
  "end": 49
}
```

No `total` / `num_pages` / `last_page_uri` — Twilio removed them; clients follow `next_page_uri`.

**Fetch** — `GET …/Messages/{Sid}.json` → single resource; unknown SID → 404 `20404`.

**Update** — `POST …/Messages/{Sid}.json`:
- `Body=""` → redacts the stored body (record retained, dashboard shows a "redacted" marker).
- `Status=canceled` → cancels a message currently in `scheduled` (otherwise 400).

**Delete** — `DELETE …/Messages/{Sid}.json` → 204. Only from terminal states
(`delivered`/`undelivered`/`failed`/`received`/`canceled`); in-flight → 409. Cascades to Media.

### 1.6 Media & Feedback subresources

**Media** — base `…/Messages/{MessageSid}/Media`:
- `GET …/Media.json` — list (envelope key `media_list`; `DateCreated`/`<`/`>` filters).
- `GET …/Media/{MediaSid}.json` — metadata: `sid` (`ME` + 32 hex), `account_sid`, `parent_sid`,
  `content_type`, `date_created`/`date_updated` (RFC 2822), `uri`.
- `GET …/Media/{MediaSid}` (no `.json`) — **302 redirect** to the stored bytes with the original
  `Content-Type` (matches Twilio). The mock downloads `MediaUrl` content at send time and stores
  it; if unreachable, it records the URL and serves a placeholder image.
- `DELETE …/Media/{MediaSid}.json` → 204.

**Feedback** — `POST …/Messages/{MessageSid}/Feedback.json`, param `Outcome` ∈
`confirmed`|`unconfirmed` (default `confirmed`). 400 unless the message was sent with
`ProvideFeedback=true`. Response: `account_sid`, `message_sid`, `outcome`, `date_created`,
`date_updated`, `uri`.

### 1.7 Segment & encoding engine

`num_segments` is computed for real, matching carrier math:

- **GSM-7** default: 160 chars single segment; concatenated messages get a 6-byte UDH per
  segment → **153** chars/segment. GSM extended chars (`^ { } \ [ ] ~ | €`) count as **2**.
- **UCS-2** fallback when any non-GSM-7 char is present: **70** single / **67** concatenated.
- **Smart Encoding** (`SmartEncoded=true`): substitution map for common Unicode look-alikes
  (curly quotes, en/em-dashes, ellipsis, non-breaking space, …) applied before encoding
  detection.
- The resource records the detected `encoding` (internal field) and the dashboard displays
  segments + encoding per message.

### 1.8 Sender types

- **E.164 numbers** — normal case.
- **Short codes** — 5–6 digit `From` accepted.
- **Alphanumeric sender IDs** — 1–11 chars from `[A-Za-z0-9 _&+-]`, at least one letter, cannot
  receive replies (dashboard reply box disabled for alpha senders in strict mode).
- **WhatsApp channel** — `whatsapp:+E164` on `To`/`From` passes through the same API; the message
  records `channel=whatsapp` and the dashboard shows a channel badge. WhatsApp-only statuses
  (`read`) can be simulated. Strict mode enforces the 24-hour session window: free-form sends to
  a number with no inbound WhatsApp message in 24h → `63016` (template required); `ContentSid`
  sends always pass.

### 1.9 (reserved)

### 1.10 Error envelope

All Twilio-shaped errors use Twilio's envelope and HTTP status:

```json
{ "code": 21211, "message": "The 'To' number +1555 is not a valid phone number.",
  "more_info": "https://www.twilio.com/docs/errors/21211", "status": 400 }
```

Codes implemented: `20003` (401 auth), `20404` (404 not found), `20429` (429 rate-limit toggle),
`21211`, `21212`, `21601`, `21602`, `21604`, `21606`, `21608`, `21610`, `21611`, `21614`,
`21617`, `30001`–`30011`, `63016`, plus Verify codes (§5).

---

## 2. Webhooks (mock → app under test)

### 2.1 Inbound message webhook

Fired when a reply is simulated (dashboard reply box or `POST /api/numbers/{number}/reply`).
Delivered to the configured inbound webhook URL (settings) — or, when Messaging Services are in
play, to the service `InboundRequestUrl` respecting `UseInboundWebhookOnNumber`. Form-encoded,
PascalCase:

`MessageSid`, `SmsSid`, `SmsMessageSid` (legacy aliases, same value), `AccountSid`,
`MessagingServiceSid` (when applicable), `From`, `To`, `Body`, `NumMedia`, `NumSegments`,
`SmsStatus=received`, `ApiVersion=2010-04-01`, `MediaUrl{N}` / `MediaContentType{N}` for each
attachment, `OptOutType` (`STOP`|`START`|`HELP`) when the body matched an opt-out keyword (§3),
and optional geo params (`FromCity`, `FromState`, `FromZip`, `FromCountry`, `ToCity`, `ToState`,
`ToZip`, `ToCountry`) with configurable defaults/overrides.

### 2.2 TwiML response handling (auto-replies)

If the app's webhook responds `2xx` with `text/xml`/`application/xml`, the mock parses TwiML the
way Twilio does:

- `<Response><Message>Hi</Message></Response>` — message text as element content, or nested
  `<Body>`; repeatable nested `<Media>` URLs; `to`/`from` attributes override defaults.
- The auto-reply is recorded as a new **outbound** message (direction `outbound-reply`) and
  appears in the dashboard thread.
- `<Redirect>` is followed (one level) to fetch the next TwiML document.
- Empty `<Response/>` → no-op. Parse errors are recorded in the webhook log.

### 2.3 Status callback webhook

Fired to the message's `StatusCallback` (or Messaging Service `StatusCallback`) on each simulated
transition through `queued`, `sending`, `sent`, `delivered` / `undelivered` / `failed`
(plus `read` for WhatsApp). Form-encoded:

`MessageSid`, `MessageStatus`, `SmsSid`, `SmsStatus` (legacy aliases), `To`, `From`,
`AccountSid`, `ApiVersion`, `MessagingServiceSid` (when applicable), `ErrorCode` (on
`undelivered`/`failed`), `RawDlrDoneDate` (`YYMMDDhhmm`, on `delivered`/`undelivered`).

### 2.4 X-Twilio-Signature

Every outgoing webhook (inbound + status callback) carries a valid `X-Twilio-Signature` computed
exactly like Twilio, so app-side `RequestValidator` middleware passes unchanged:

1. Take the full request URL as called (scheme + host + path + query).
2. Sort POST params by key (byte order); append `key + value` (no separators) to the URL.
3. HMAC-SHA1 with the configured auth token as key; base64-encode.

### 2.5 Webhook delivery log

Every delivery attempt is recorded: kind (inbound / status-callback), URL, request params,
response status + body (truncated), duration, error. Exposed via `GET /api/webhook-log`, shown
in the dashboard with a **retry** action (`POST /api/webhook-log/{id}/retry`).

---

## 3. Opt-Out Engine

Mirrors Twilio's default + Advanced Opt-Out behavior:

- **Opt-out keywords** (inbound body, case-insensitive, exact match after trim): `STOP`,
  `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`, `REVOKE`, `OPTOUT` → records an opt-out for
  the (recipient, sender) pair and sends the confirmation auto-reply.
- **Opt-in keywords**: `START`, `YES`, `UNSTOP` → clears the opt-out + confirmation.
- **Help keywords**: `HELP`, `INFO` → help auto-reply.
- Keyword lists and confirmation/help message bodies are configurable in settings (mirrors
  Advanced Opt-Out); matched keyword type is passed to the app webhook as `OptOutType`.
- **Strict mode**: sending to an opted-out pair → 400, error `21610`, message not created.
  Permissive mode: send succeeds but the dashboard flags it.
- Dashboard: opt-out badge per number + manual toggle; `GET /api/optouts`, `PUT /api/optouts`.

---

## 4. Messaging Services (v1) — `/v1/Services`

CRUD + sender pools, ISO 8601 dates (v1/v2 APIs use ISO 8601, **not** RFC 2822):

- `POST /v1/Services`, `GET /v1/Services` (paged), `GET/POST/DELETE /v1/Services/{Sid}`.
- Settable fields: `FriendlyName` (required, ≤64), `InboundRequestUrl`, `InboundMethod`,
  `FallbackUrl`, `FallbackMethod`, `StatusCallback`, `StickySender` (default true),
  `SmartEncoding`, `ScanMessageContent` (`inherit`|`enable`|`disable`), `AreaCodeGeomatch`,
  `ValidityPeriod`, `Usecase`, `UseInboundWebhookOnNumber`; obsolete fields (`MmsConverter`,
  `FallbackToLongCode`, `SynchronousValidation`) accepted and stored.
- Resource: `sid` (`MG` + 32 hex), `account_sid`, all settings, `date_created`/`date_updated`
  (ISO 8601), `url`, `links` to subresources.
- **Sender pool subresources**:
  - `/v1/Services/{Sid}/PhoneNumbers` — add by `PhoneNumberSid` (mock also accepts a raw
    `PhoneNumber` for convenience); fields include `phone_number`, `country_code`,
    `capabilities`.
  - `/v1/Services/{Sid}/AlphaSenders` — add by `AlphaSender` (validated per §1.8).
  - `/v1/Services/{Sid}/ShortCodes` — add by short code.
- **Send behavior** with `MessagingServiceSid`: message starts `accepted`; the pool picks `From`
  (sticky sender per recipient when enabled; area-code geomatch when enabled; otherwise
  round-robin), then `queued → …`. Service-level `StatusCallback`, `SmartEncoding`,
  `ValidityPeriod` apply when not overridden per-message. Empty pool → `failed` with `21606`.

---

## 5. Verify API (v2) — `/v2/Services`

Only the `sms` channel is functional; other channels are rejected (`60200`) — params for other
channels are accepted and stored on the service.

- **Service CRUD**: `POST/GET /v2/Services`, `GET/POST/DELETE /v2/Services/{Sid}`. Fields:
  `FriendlyName` (≤32, required), `CodeLength` (4–10, default 6), `CustomCodeEnabled`,
  `SkipSmsToLandlines`, `Psd2Enabled`, `DoNotShareWarningEnabled`, `DtmfInputRequired`,
  `TtsName`, `LookupEnabled`. Resource: `sid` (`VA` + 32 hex), ISO 8601 dates, `url`, `links`.
- **Start verification** — `POST /v2/Services/{Sid}/Verifications`:
  - Params: `To` (required), `Channel=sms` (required), `CustomCode` (needs `CustomCodeEnabled`),
    `Locale`.
  - Generates a code of `CodeLength` digits and **records it as a real SMS message** ("Your
    verification code is: 123456") — it appears in the dashboard thread, fires status callbacks,
    and is picked up by `latest-code`.
  - Response: `sid` (`VE` + 32 hex), `service_sid`, `account_sid`, `to`, `channel`,
    `status=pending`, `valid=false`, `send_code_attempts` (array of attempt records), dates, `url`.
  - Re-POSTing for the same `To` re-sends (new message, same verification, attempt appended);
    more than 5 sends → `60203`.
- **Check** — `POST /v2/Services/{Sid}/VerificationCheck` with `Code` + (`To` or
  `VerificationSid`):
  - Correct code → `status=approved`, `valid=true` (verification consumed: later checks → 404
    `20404`, like Twilio).
  - Wrong code → `status=pending`, `valid=false`; more than 5 failed checks →
    `max_attempts_reached`, error `60202`.
  - Expired (default TTL 10 min, configurable) or unknown → 404 `20404`.
- **Cancel** — `POST /v2/Services/{Sid}/Verifications/{VerificationSid}` with `Status=canceled`.
- Statuses: `pending`, `approved`, `canceled`, `max_attempts_reached`, `expired`, `failed`.
- Dashboard: verifications panel per number — expected code, attempts used, expiry countdown.

---

## 6. Lookup API (v2) — `GET /v2/PhoneNumbers/{number}`

Backed by the `phonenumbers` library for real parsing/formatting:

- Default (`validation` package): `calling_country_code`, `country_code` (ISO 3166-1 alpha-2),
  `phone_number` (E.164), `national_format`, `valid` (bool), `validation_errors[]`
  (e.g. `TOO_SHORT`, `INVALID_COUNTRY_CODE`), `url`; all data-package fields present but `null`.
- Query params: `Fields` (comma-separated packages), `CountryCode` (for national-format input).
- `Fields=line_type_intelligence` → returns configurable canned data
  (`{type: "mobile"|"landline"|"nonFixedVoip"|…, carrier_name, …}`); default `mobile`, with
  per-number overrides in settings so tests can exercise "reject VoIP/landline" logic. The same
  overrides drive strict-mode `21614` on send.
- Other packages (`caller_name`, `sim_swap`, …) return `null` (documented as not emulated).

---

## 7. Internal API (dashboard + test automation)

- `GET /api/numbers` — all numbers with message counts, latest message preview, unread state,
  opt-out flag.
- `GET /api/numbers/{number}/messages` — conversation thread (paginated).
- `POST /api/numbers/{number}/reply` — simulate an inbound SMS from this number: `body`, optional
  `to` (defaults to the thread's app number), optional media URLs + geo overrides. Fires the
  inbound webhook (§2.1) and TwiML handling (§2.2).
- `GET /api/numbers/{number}/latest-code` — most recent OTP code sent **to** this number.
  Default patterns: 4–8 digit runs (word-boundary), aware of Verify-generated codes;
  `?regex=` override with a capture group. Returns code + message SID + age. 404 if none.
- `DELETE /api/messages` — clear all; `DELETE /api/numbers/{number}/messages` — clear thread.
- `GET /api/settings` / `PUT /api/settings`:
  - inbound webhook URL + method
  - account SID + auth token (used for signatures and strict-mode auth)
  - status-callback simulation: per-status delays, global failure rate, per-number forced
    outcome rules (`{to_suffix, status, error_code}`)
  - strictness toggles: auth, E.164 validation, opt-out enforcement, trial mode (+ verified
    numbers list), rate-limit simulation
  - geo param defaults; opt-out keyword + confirmation customization; Verify TTL;
    Lookup line-type overrides
- `GET /api/webhook-log` (paginated, filterable), `POST /api/webhook-log/{id}/retry`.
- `GET /api/optouts`, `PUT /api/optouts` (set/clear a pair).
- `WS /api/ws` — events: `message.created`, `message.status_changed`, `messages.cleared`,
  `verification.created`, `verification.updated`, `webhook.delivered`.

---

## 8. Frontend (Dashboard)

Inbox-style layout, dark mode supported:

- **Sidebar**: phone numbers with message-count badges, latest message preview, unread indicator,
  opt-out badge, search/filter.
- **Thread view** (`/numbers/:number`): chat-style conversation — outbound and simulated inbound
  bubbles; per-message detail: SID, status **timeline** (queued→sending→sent→delivered ticks),
  error-code chip with description, segments + encoding, media attachments, channel badge
  (SMS/MMS/WhatsApp), timestamps.
- **Reply box**: send a simulated inbound SMS (with media URLs); disabled for alphanumeric
  senders in strict mode.
- **OTP highlight**: detected verification codes rendered with a copy button.
- **Verifications panel**: active Verify verifications for the number — expected code, attempts,
  expiry countdown.
- **Webhook log**: deliveries with status/duration, expandable request/response, retry button.
- **Settings page**: everything in §7 settings, grouped (Webhooks / Simulation / Strictness /
  Opt-out / Verify / Lookup), plus clear-all.
- **Live updates**: WebSocket events invalidate TanStack Query caches
  (`queryClient.invalidateQueries`) — no manual cache surgery.
- **Empty states + toasts** via shadcn/ui components.

---

## 9. Data Model (SQLModel)

- **Message**: `sid` (PK), `account_sid`, `direction`, `from_number`, `to_number`, `body`,
  `status`, `error_code`, `error_message`, `num_segments`, `num_media`, `encoding`
  (gsm7|ucs2), `channel` (sms|mms|whatsapp), `messaging_service_sid`, `schedule_type`,
  `send_at`, `validity_period`, `status_callback_url`, `price`, `provide_feedback`,
  `feedback_outcome`, `date_created`, `date_sent`, `date_updated`, `raw_params` (JSON).
- **MediaItem**: `sid` (`ME…`, PK), `message_sid` (FK), `content_type`, `source_url`,
  `blob_path`, dates.
- **MessagingService**: `sid` (`MG…`, PK), settings columns per §4, dates.
- **ServiceSender**: id, `service_sid` (FK), `kind` (phone_number|alpha_sender|short_code),
  `value`, `capabilities`, dates.
- **VerifyService**: `sid` (`VA…`, PK), `friendly_name`, `code_length`, `custom_code_enabled`,
  other settings, dates.
- **Verification**: `sid` (`VE…`, PK), `service_sid` (FK), `to`, `channel`, `code`, `status`,
  `check_attempts`, `send_attempts` (JSON), `expires_at`, dates.
- **OptOut**: id, `recipient`, `sender`, `opted_out` (bool), dates.
- **WebhookDelivery**: id, `kind` (inbound|status_callback), `url`, `request_params` (JSON),
  `response_status`, `response_body` (truncated), `duration_ms`, `error`, `message_sid`,
  `created_at`.
- **Settings**: singleton row — all §7 settings (JSON columns for structured groups).

---

## 10. Repo Layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, static file serving
│   │   ├── config.py          # env-driven settings
│   │   ├── db.py              # engine/session
│   │   ├── models.py          # SQLModel models
│   │   ├── twilio_api.py      # 2010-04-01 Messages + Media + Feedback routes
│   │   ├── messaging_v1.py    # Messaging Services v1 routes
│   │   ├── verify_v2.py       # Verify v2 routes
│   │   ├── lookup_v2.py       # Lookup v2 routes
│   │   ├── internal_api.py    # dashboard/test routes
│   │   ├── ws.py              # WebSocket manager
│   │   ├── segments.py        # GSM-7/UCS-2 segment engine + smart encoding
│   │   ├── otp.py             # code extraction
│   │   ├── optout.py          # keyword engine
│   │   ├── lifecycle.py       # status simulation scheduler
│   │   ├── signature.py       # X-Twilio-Signature
│   │   ├── twiml.py           # TwiML response parsing
│   │   ├── errors.py          # Twilio error envelope + code registry
│   │   └── webhooks.py        # outbound webhook delivery (httpx) + log
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── routes/            # TanStack Router file routes
│   │   ├── components/        # shadcn/ui-based components
│   │   ├── api/               # TanStack Query hooks + WS client
│   │   └── lib/
│   └── ...
├── Dockerfile                 # multi-stage: build frontend → copy into python image
├── compose.yaml
├── Caddyfile                  # dev proxy: one port for API + Vite dev server
├── justfile
├── README.md
└── SPEC.md
```

## 11. Justfile Recipes

- `just dev` — run backend (uvicorn --reload on :8825) + frontend (vite dev on :5173) behind
  Caddy on :8025 (see `Caddyfile`), so dev serves everything on one port exactly like the
  production container; Vite also proxies `/api`, `/2010-04-01`, `/v1`, `/v2` for direct :5173
  access
- `just test` — pytest + vitest
- `just build` — docker build
- `just up` / `just down` — compose up/down
- `just lint` / `just fmt` — ruff + eslint/prettier

## 12. Build Phases

1. **Scaffold**: repo layout, FastAPI skeleton with health check, Vite + React + Tailwind +
   shadcn init, Dockerfile, compose, justfile — `just dev` and `just test` work end to end.
2. **Capture**: Messages send/list/fetch with pagination, segment engine, SQLite persistence,
   numbers sidebar + thread view.
3. **Live updates**: WebSocket events + TanStack Query invalidation.
4. **Lifecycle**: status simulation, StatusCallback delivery + X-Twilio-Signature, webhook log,
   update (redact/cancel) + delete, scheduled sends.
5. **Two-way**: reply UI → inbound webhooks, TwiML auto-reply parsing, opt-out engine, MMS media
   subresource.
6. **Verification**: OTP extraction + `latest-code`, Verify v2 emulation, verifications panel +
   OTP highlight/copy.
7. **Services + Lookup**: Messaging Services v1 (sender pools, `accepted` flow), Lookup v2.
8. **Polish**: strict-mode completeness, search, dark mode, README with Twilio-switching docs
   (Python + Node SDK snippets), example Playwright/pytest E2E snippets.

Phases 1–8 shipped in v0.1.0. The phases below came out of a post-v0.1.0 gap review against
Twilio's real surface and Mailpit's feature set.

9. **API fidelity completion**:
   - Feedback subresource: `POST …/Messages/{Sid}/Feedback.json` (`Outcome`
     `confirmed`|`unconfirmed`, requires `ProvideFeedback=true`) — currently advertised in
     `subresource_uris` but unimplemented
   - `ContentSid` + `ContentVariables`: render a plain-text body from the variables instead of
     storing an empty body
   - GET webhook delivery: honor `inbound_webhook_method` (currently stored but always POSTs),
     including Twilio's query-param signature variant
   - WhatsApp depth: 24-hour session window enforcement in strict mode (free-form send outside
     the window → `63016`; `ContentSid` sends always pass) and `read` status simulation after
     `delivered`
   - Strict auth: accept API keys (`SK…` + secret) alongside `AC…` + token
   - Real `PageSize`/`Page` pagination for the v1/v2 list envelopes and the Media list
     (+ `DateCreated` filters)
   - Messaging Service `fallback_url`: invoked when the inbound handler errors or returns non-2xx
   - `IncomingPhoneNumbers` (2010-04-01) emulation: per-number `SmsUrl`/`SmsMethod`/
     `StatusCallback`, with Twilio's routing precedence (service `InboundRequestUrl` vs
     `UseInboundWebhookOnNumber` vs number `SmsUrl`)
10. **Dashboard & workflow UX**:
    - **Message tags** (Mailpit-style, for organizing manual testing): manual tags on
      messages/threads plus auto-tag rules in settings (match To/From/body regex → tag);
      tag chips in the sidebar and thread view; filter by tag in search (`tag:` prefix or
      filter UI); Twilio's `Tags` send parameter surfaced as tags on the message; tags in the
      internal API and WS events; `GET /api/tags` for the filter list
    - Unread indicators per thread (read-state tracked when a thread is opened)
    - Message detail drawer: full Twilio-shaped JSON, original request params (`raw_params`),
      copy SID, per-message delete
    - Retention: auto-purge setting (max message age / count), like Mailpit
    - Export: download a thread or all messages as JSON/CSV
    - Webhook log filters (kind, message, status) and a scheduled-messages view
    - Optional dashboard auth token for shared/staging deployments
11. **Conformance & distribution**:
    - SDK conformance job in CI: run real `twilio-python` and `twilio-node` clients against the
      container (send, paginate, fetch media, Verify flow, Lookup) — turns "Twilio-shaped" into
      a tested guarantee
    - Playwright E2E suite in CI (send → live update → reply → TwiML auto-reply → OTP copy)
    - Multi-arch Docker images (`linux/amd64,linux/arm64`)
    - Seed/fixture API (`POST /api/seed`) for demo data and screenshots
    - Webhook chaos options: injectable delivery failures/latency and Twilio-style status
      callback retries, for testing app-side resilience

12. **Mailpit parity** (from a feature comparison against Mailpit):
    - **Release / forwarding to real Twilio** (Mailpit's SMTP relay analog): configure real
      Twilio credentials (`real_account_sid`/`real_auth_token`/`real_from_number`) plus a
      mandatory recipient **allowlist**; `POST /api/messages/{sid}/release` re-sends a captured
      message through api.twilio.com (optionally to an override recipient); optional
      `auto_forward_to` forwards every captured outbound message to a tester's phone.
      Every release attempt is recorded in the webhook log (kind `release`). Without an
      allowlist entry the release is refused — the mock must never text real people by accident.
    - **Search operators** (Mailpit's advanced search analog): `from:`, `to:`, `status:`,
      `is:unread`, `has:media`, `before:`/`after:` (dates), alongside the existing `tag:` and
      free text, all combinable in the sidebar search and `GET /api/numbers?q=`.
    - **Capture webhook** (Mailpit's received-message webhook): `capture_webhook_url` receives a
      JSON POST for every captured message (any direction), fire-and-forget so the Twilio send
      path never blocks; logged with kind `capture`.
    - **Browser notifications**: opt-in toggle; new messages raise a desktop notification when
      the dashboard tab is hidden.
    - **Encoding check** (Mailpit's HTML-check analog): the message detail drawer explains the
      segment math — encoding, length, segment count, the exact characters that force UCS-2,
      and what Smart Encoding would save.
    - Deliberately skipped: POP3 (no SMS analog), single-binary distribution (Docker covers it),
      link checking (future), retention stays off by default (test history is precious;
      Mailpit defaults to keeping 500).
## 13. Pointing SDKs / Apps at the Mock

Everything is served on one port; route families are disambiguated by path
(`/2010-04-01/…`, `/v1/Services`, `/v2/Services`, `/v2/PhoneNumbers`), so raw-HTTP apps need a
single base URL override (`TWILIO_API_BASE_URL=http://localhost:8025`).

Official SDKs pin per-product hosts; documented overrides (full snippets land in the README in
phase 8):

```python
# twilio-python
from twilio.rest import Client
client = Client(account_sid, auth_token)
client.api.base_url = "http://localhost:8025"        # Programmable Messaging
client.verify.base_url = "http://localhost:8025"     # Verify
client.messaging.base_url = "http://localhost:8025"  # Messaging Services
client.lookups.base_url = "http://localhost:8025"    # Lookup
```

```ts
// twilio-node
const client = twilio(accountSid, authToken);
client.api.baseUrl = "http://localhost:8025";
client.verify.baseUrl = "http://localhost:8025";
client.messaging.baseUrl = "http://localhost:8025";
client.lookups.baseUrl = "http://localhost:8025";
```

Known limitation: SDK base-URL override mechanics vary by SDK version; the README documents the
tested patterns per language, and plain `httpx`/`fetch` integration is always safe.

## 14. Non-Goals

- No real SMS delivery, no carrier integration.
- No auth on the dashboard (local dev tool).
- No multi-tenant support; single project per instance.
- Out of scope: voice, email, RCS-specific features, WhatsApp template approval flows
  (`ContentSid` accepted, rendered as plain text), Lookup data packages beyond
  `line_type_intelligence`.
