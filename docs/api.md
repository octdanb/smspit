# Internal API

Everything the dashboard does goes through the internal REST API under `/api`, so it's all
scriptable — test automation, CI hooks, seeding demo data. It's JSON (unlike the form-encoded
Twilio-shaped routes) and unauthenticated unless `SMSPIT_DASHBOARD_TOKEN` is set, in which
case requests need an `X-Smspit-Token` header.

For settings keys and their meanings, see [configuration.md](configuration.md).

## Test automation

The endpoints most useful from a test suite:

- `GET /api/numbers/{number}/latest-code` — the most recent OTP sent **to** a number. Detects
  4–8 digit codes by default; pass `?regex=` with a capture group for custom formats. Returns
  `{code, message_sid, body, date_created, age_seconds}`, or 404 when there's none.
- `POST /api/numbers/{number}/reply` — simulate an inbound SMS from that number:
  `{"body": "...", "to"?: "...", "media_urls"?: [...], "geo"?: {...}}`. Fires your app's
  inbound webhook (signed), handles the TwiML response, and returns the recorded message.
- `POST /api/seed` — load fixtures. Empty body loads the demo conversations; or pass
  `{"messages": [{"from_number", "to_number", "body", "direction"?, "tags"?}]}`. Seeded
  messages skip lifecycle simulation and webhooks.
- `PUT /api/settings` — flip behavior mid-test (forced failure rules, strict mode, webhook
  chaos…). Send only the keys you're changing.
- `DELETE /api/messages` — clear everything between tests;
  `DELETE /api/numbers/{number}/messages` clears one thread.

## Messages & threads

- `GET /api/numbers?q=` — all numbers with counts, previews, unread state, tags. The `q`
  search matches numbers and full message bodies, and supports the same operators as the
  dashboard search box: `tag:`, `from:`, `to:`, `status:`, `has:media`, `is:unread`, and
  `before:`/`after:YYYY-MM-DD`, combinable with free text.
- `GET /api/numbers/{number}/messages?page=&page_size=` — one thread, oldest first.
- `POST /api/numbers/{number}/read` — mark a thread read.
- `GET /api/messages/{sid}` — full detail: the Twilio-shaped resource, original request
  params, tags, media, status callbacks, and the encoding check (which characters force
  UCS-2 and what Smart Encoding would save).
- `DELETE /api/messages/{sid}` — delete one message (any status, unlike the Twilio endpoint).
- `GET /api/export?format=json|csv&number=` — download everything (or one thread) as a file.
- `GET /api/scheduled` / `POST /api/scheduled/{sid}/cancel` — pending scheduled sends.
- `GET /api/media/{media_sid}` — stored MMS bytes.

## Tags

- `GET /api/tags` — all tags in use (for filter UIs).
- `PUT /api/messages/{sid}/tags` — replace a message's tags: `{"tags": ["otp", "signup"]}`.

Auto-tagging rules live in settings (`auto_tag_rules`).

## Verifications, opt-outs, webhooks

- `GET /api/numbers/{number}/verifications` — active Verify v2 verifications with expected
  codes, attempts, and expiry.
- `GET /api/optouts` / `PUT /api/optouts` — list or set opt-out state:
  `{"recipient": "+1555…", "sender": "+1444…" | "*", "opted_out": true}` (a `*` sender
  applies to all of the recipient's pairs).
- `GET /api/webhook-log?kind=&result=&message_sid=` — every webhook delivery attempt with
  request, response, duration, and error. `POST /api/webhook-log/{id}/retry` re-sends one.
- `POST /api/messages/{sid}/release` — re-send a captured message through real Twilio
  (optionally `{"to": "+1555…"}`); refused unless the recipient is on the release allowlist.

## Live updates

`WS /api/ws` broadcasts JSON events as things happen: `message.created`,
`message.status_changed`, `messages.cleared`, `verification.created`, `verification.updated`,
and `webhook.delivered`. The dashboard uses these to invalidate its query cache; anything else
(a test waiting for a message, a custom notifier) can subscribe the same way.

## Health & version

`GET /api/health` — `{"status": "ok"}`, and `GET /api/version` — `{"version": "…"}`. Neither is
ever gated by the dashboard token, so probes and the version banner always work.
