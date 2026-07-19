# Security Policy

## Reporting a vulnerability

Please report security issues privately via GitHub's
[private vulnerability reporting](https://github.com/octdanb/octavenz-smspit/security/advisories/new)
rather than opening a public issue. We'll acknowledge and work with you on a fix.

## Scope and intended use

smspit is a **testing tool** that emulates Twilio. It is not hardened for use as
a public, internet-facing production service. When hosting a shared instance
(e.g. a UAT box):

- Set `SMSPIT_DASHBOARD_TOKEN` so the dashboard and internal API require a token.
- Put it behind TLS-terminating ingress.
- Keep `SMSPIT_ALLOW_PRIVATE_MEDIA` unset so the server refuses to fetch media
  URLs pointing at internal/loopback addresses (SSRF protection).
- Treat any real Twilio credentials configured for the release feature as
  secrets — they are never returned by the API and only ever send to numbers on
  the release allowlist.

See [docs/configuration.md](docs/configuration.md) for details.
