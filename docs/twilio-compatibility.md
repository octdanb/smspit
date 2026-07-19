# Twilio compatibility

smspit emulates four Twilio API families closely enough that the official SDKs work unchanged
— CI runs the real `twilio-python` and `twilio-node` clients against every build. This page
documents what's implemented and the fidelity details that tend to matter.

Everything is served on one port, routed by path prefix (`/2010-04-01`, `/v1`, `/v2`), so a
single base-URL override covers all four families.

## Fidelity notes worth knowing

These are the quirks of the real Twilio API that smspit reproduces (and that trip up
hand-rolled fakes):

- `num_segments`, `num_media`, and `price` are JSON **strings** (`"1"`, `"0"`, `"-0.00750"`).
- Dates on the 2010-04-01 API are **RFC 2822** (`Fri, 24 May 2019 17:44:46 +0000`); the v1/v2
  APIs use ISO 8601.
- List responses use Twilio's pagination envelope (`first_page_uri`, `next_page_uri`,
  `PageToken`, …) with no `total` or `num_pages` — clients follow `next_page_uri`.
- Errors use Twilio's envelope: `{"code": 21211, "message": "…", "more_info": "…", "status": 400}`.
- The media binary lives at the non-`.json` URL and is served via a **302 redirect**, like
  Twilio.
- `num_segments` is computed for real: GSM-7 (160, or 153 per segment when concatenated,
  extended chars like `€ [ ] ~` counting double) vs UCS-2 (70 / 67), with Smart Encoding
  substitution when `SmartEncoded=true`.
- Every outgoing webhook carries a valid `X-Twilio-Signature` (HMAC-SHA1 over the URL plus
  sorted params, keyed by the configured auth token), so app-side `RequestValidator`
  middleware passes unchanged. GET webhooks are signed over the full URL including the query
  string, exactly like Twilio signs GETs.

## Programmable Messaging (2010-04-01)

`POST /2010-04-01/Accounts/{AccountSid}/Messages.json` accepts the full parameter set: `To`,
`From` or `MessagingServiceSid`, `Body` / `MediaUrl` (repeatable) / `ContentSid` +
`ContentVariables`, `StatusCallback`, `ScheduleType=fixed` + `SendAt`, `SmartEncoded`,
`ValidityPeriod`, `SendAsMms`, `ProvideFeedback`, `Tags`, and the rest — obsolete parameters
(`MaxPrice`, `ForceDelivery`) are accepted and ignored, matching Twilio.

- **List / fetch / update / delete**: `To`/`From`/`DateSent` filters, `PageSize`/`Page`/
  `PageToken` pagination; update with `Body=""` redacts, `Status=canceled` cancels a scheduled
  message; delete only succeeds from terminal states (409 otherwise) and cascades to media.
- **Statuses**: the full wire set — `accepted`, `scheduled`, `queued`, `sending`, `sent`,
  `delivered`, `undelivered`, `failed`, `receiving`, `received`, `read`, `canceled`. Direct
  sends walk `queued → sending → sent → delivered` (configurable); Messaging Service sends
  start at `accepted`; scheduled sends wait in `scheduled` until `SendAt`.
- **Media**: `MediaUrl` content is downloaded and stored at send time (placeholder when
  unreachable); list, metadata, binary redirect, and delete all work.
- **Feedback**: `POST …/Messages/{Sid}/Feedback.json` with `Outcome`, gated on
  `ProvideFeedback=true`.
- **Sender types**: E.164 numbers, 5–6 digit short codes, alphanumeric sender IDs (validated;
  can't receive replies), and `whatsapp:+E164` channel addressing (channel badge in the
  dashboard, `read` status simulation, and strict-mode enforcement of the 24-hour session
  window — free-form sends outside it get `63016`; `ContentSid` sends always pass).
- **IncomingPhoneNumbers**: per-number `SmsUrl`/`SmsMethod`/`StatusCallback`, with Twilio's
  inbound routing precedence (Messaging Service `InboundRequestUrl` vs
  `UseInboundWebhookOnNumber` vs the number's `SmsUrl` vs the global setting).

## Webhooks to your app

- **Inbound messages** (replies typed in the dashboard or posted to the internal API) are
  delivered form-encoded with the full Twilio parameter set — `MessageSid`, `From`, `To`,
  `Body`, `NumMedia`, `MediaUrl{N}`, `OptOutType` when a keyword matched, optional geo params.
- **TwiML responses** are handled the way Twilio handles them: a `<Response><Message>` reply
  (element text or nested `<Body>`/`<Media>`, `to`/`from` attributes, one `<Redirect>` level)
  is recorded as an outbound message and shows up in the thread. An empty `<Response/>` is a
  no-op; parse errors land in the webhook log.
- **Status callbacks** fire on every simulated transition with `MessageSid`, `MessageStatus`,
  `ErrorCode` on failures, and `RawDlrDoneDate` on delivery.
- **Fallback URLs**: when an inbound handler errors or returns non-2xx, the Messaging Service
  `FallbackUrl` is tried.
- Every delivery attempt — including retries and chaos-induced failures — is recorded in the
  webhook log with request, response, duration, and a retry button.

## Opt-outs

Inbound `STOP`/`UNSUBSCRIBE`/etc. record an opt-out for the (recipient, sender) pair and send
the confirmation auto-reply; `START`/`YES` opt back in; `HELP`/`INFO` get the help reply.
Keyword lists and reply bodies are configurable, mirroring Twilio's Advanced Opt-Out. With
`enforce_optouts` on, sends to an opted-out pair are rejected with `21610`.

## Messaging Services (v1)

Service CRUD with the real field set (`StickySender`, `SmartEncoding`, `AreaCodeGeomatch`,
`UseInboundWebhookOnNumber`, …) plus the three sender-pool subresources (`/PhoneNumbers`,
`/AlphaSenders`, `/ShortCodes`). Sending with `MessagingServiceSid` starts at `accepted` and
picks `From` from the pool — sticky sender per recipient, area-code geomatch when enabled,
round-robin otherwise. Service-level `StatusCallback`, `SmartEncoding`, and `ValidityPeriod`
apply when not overridden per message; an empty pool fails the send with `21606`.

## Verify (v2)

Service CRUD (`CodeLength`, `CustomCodeEnabled`, …) and the full verification flow: starting a
verification generates a code and **records it as a real SMS message**, so it appears in the
dashboard thread and is picked up by `latest-code`. Re-sends append attempts (more than 5 →
`60203`); checks approve on the right code, count failures (more than 5 →
`max_attempts_reached`, `60202`), and 404 once approved or expired, like Twilio. Only the
`sms` channel is functional; others are rejected with `60200`.

## Lookup (v2)

`GET /v2/PhoneNumbers/{number}` with real parsing via the `phonenumbers` library:
`valid`, `phone_number`, `national_format`, `country_code`, `validation_errors`, and
`Fields=line_type_intelligence` returning configurable per-number line types (default
`mobile`) — so tests can exercise "reject VoIP/landline" logic. Other data packages return
`null`.

## Error codes

Strict-mode checks and simulated failures raise real Twilio codes, including:

| Code | Meaning |
|---|---|
| `20003` | Authentication failed (`strict_auth`) |
| `20404` | Resource not found |
| `20429` | Rate limited (`rate_limit_per_minute`) |
| `21211` / `21212` | Invalid `To` / `From` (`strict_validation`) |
| `21602` / `21604` / `21617` | Missing body / missing `To` / body over 1600 chars |
| `21606` | `From` not usable (e.g. empty Messaging Service pool) |
| `21608` | Unverified recipient (`trial_mode`) |
| `21610` | Recipient has opted out (`enforce_optouts`) |
| `21614` | `To` is not a mobile number (per Lookup line-type overrides) |
| `30003`–`30008` | Delivery failures (`forced_rules` / `failure_rate`) |
| `60200` / `60202` / `60203` | Verify: bad channel / max check attempts / max send attempts |
| `63016` | WhatsApp free-form message outside the 24-hour session window |

## What's not emulated

No real SMS delivery or carrier integration, single-tenant only. Voice, email, RCS, WhatsApp
template approval flows (`ContentSid` is accepted and rendered as plain text), and Lookup data
packages beyond `line_type_intelligence` are out of scope.
