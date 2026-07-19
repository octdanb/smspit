"""Outbound webhook delivery (status callbacks now, inbound messages in phase 5).

Every attempt is signed with X-Twilio-Signature and recorded in the
WebhookDelivery log, success or failure.
"""

import json
import time
from datetime import UTC, datetime

import httpx
from sqlmodel import Session

from .db import get_engine, get_settings
from .models import Message, WebhookDelivery
from .signature import compute_signature
from .ws import manager

# Tests inject an httpx.MockTransport here to capture deliveries.
_transport: httpx.AsyncBaseTransport | None = None

RESPONSE_BODY_LIMIT = 2000
API_VERSION = "2010-04-01"


def build_status_callback_params(message: Message, status: str) -> dict[str, str]:
    params = {
        "MessageSid": message.sid,
        "MessageStatus": status,
        "SmsSid": message.sid,
        "SmsStatus": status,
        "To": message.to_number,
        "From": message.from_number,
        "AccountSid": message.account_sid,
        "ApiVersion": API_VERSION,
    }
    if message.messaging_service_sid:
        params["MessagingServiceSid"] = message.messaging_service_sid
    if message.error_code is not None:
        params["ErrorCode"] = str(message.error_code)
    if status in ("delivered", "undelivered"):
        params["RawDlrDoneDate"] = datetime.now(UTC).strftime("%y%m%d%H%M")
    return params


async def deliver(
    kind: str,
    url: str,
    params: dict[str, str],
    message_sid: str | None = None,
) -> WebhookDelivery:
    """POST form-encoded params to url, signed; record the attempt in the log."""
    with Session(get_engine()) as session:
        auth_token = get_settings(session).auth_token

    headers = {"X-Twilio-Signature": compute_signature(auth_token, url, params)}
    started = time.monotonic()
    response_status: int | None = None
    response_body: str | None = None
    error: str | None = None
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=10) as client:
            response = await client.post(url, data=params, headers=headers)
        response_status = response.status_code
        response_body = response.text[:RESPONSE_BODY_LIMIT]
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    delivery = WebhookDelivery(
        kind=kind,
        url=url,
        request_params=json.dumps(params),
        response_status=response_status,
        response_body=response_body,
        duration_ms=int((time.monotonic() - started) * 1000),
        error=error,
        message_sid=message_sid,
    )
    with Session(get_engine()) as session:
        session.add(delivery)
        session.commit()
        session.refresh(delivery)

    await manager.broadcast(
        "webhook.delivered",
        {
            "id": delivery.id,
            "kind": kind,
            "url": url,
            "response_status": response_status,
            "error": error,
        },
    )
    return delivery


async def deliver_status_callback(message: Message, status: str) -> WebhookDelivery | None:
    if not message.status_callback_url:
        return None
    params = build_status_callback_params(message, status)
    return await deliver("status_callback", message.status_callback_url, params, message.sid)
