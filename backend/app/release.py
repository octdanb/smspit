"""Release captured messages through REAL Twilio (Mailpit's SMTP-relay analog).

Safety first: a release only ever goes to a number on the configured
allowlist — the mock must never text real people by accident. Every attempt
is recorded in the webhook log with kind "release".
"""

import json
import time

import httpx
from sqlmodel import Session

from .db import get_engine, get_settings
from .models import Message, WebhookDelivery
from .ws import manager

# Tests inject an httpx.MockTransport here to stand in for api.twilio.com.
_transport: httpx.AsyncBaseTransport | None = None

TWILIO_API = "https://api.twilio.com"


class ReleaseError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


async def release_message(
    session: Session, message: Message, to_override: str | None = None
) -> dict:
    settings = get_settings(session)
    if not (settings.real_account_sid and settings.real_auth_token and settings.real_from_number):
        raise ReleaseError(
            400,
            "Release is not configured: set real_account_sid, real_auth_token and "
            "real_from_number in settings.",
        )
    to = (to_override or message.to_number).strip()
    allowlist = json.loads(settings.release_allowlist or "[]")
    if to not in allowlist:
        raise ReleaseError(
            403,
            f"{to} is not on the release allowlist — add it to release_allowlist first. "
            "The mock never texts numbers you haven't explicitly allowed.",
        )

    url = f"{TWILIO_API}/2010-04-01/Accounts/{settings.real_account_sid}/Messages.json"
    params = {"To": to, "From": settings.real_from_number, "Body": message.body}

    started = time.monotonic()
    response_status: int | None = None
    response_body: str | None = None
    error: str | None = None
    real_sid: str | None = None
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=15) as client:
            response = await client.post(
                url,
                data=params,
                auth=(settings.real_account_sid, settings.real_auth_token),
            )
        response_status = response.status_code
        response_body = response.text[:2000]
        if 200 <= response.status_code < 300:
            real_sid = response.json().get("sid")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    delivery = WebhookDelivery(
        kind="release",
        url=url,
        method="POST",
        request_params=json.dumps(params),
        response_status=response_status,
        response_body=response_body,
        duration_ms=int((time.monotonic() - started) * 1000),
        error=error,
        message_sid=message.sid,
    )
    with Session(get_engine()) as log_session:
        log_session.add(delivery)
        log_session.commit()
        log_session.refresh(delivery)

    await manager.broadcast(
        "webhook.delivered",
        {
            "id": delivery.id,
            "kind": "release",
            "url": url,
            "response_status": response_status,
            "error": error,
        },
    )

    ok = error is None and response_status is not None and 200 <= response_status < 300
    return {
        "released": ok,
        "to": to,
        "from": settings.real_from_number,
        "real_sid": real_sid,
        "response_status": response_status,
        "error": error,
    }


async def auto_forward(message_sid: str) -> None:
    """Forward a captured outbound message to the configured tester number."""
    from sqlmodel import select

    with Session(get_engine()) as session:
        settings = get_settings(session)
        if not settings.auto_forward_to:
            return
        message = session.exec(select(Message).where(Message.sid == message_sid)).first()
        if message is None:
            return
        try:
            await release_message(session, message, to_override=settings.auto_forward_to)
        except ReleaseError:
            pass  # misconfiguration is visible via the manual release path
