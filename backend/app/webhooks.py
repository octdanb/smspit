"""Outbound webhook delivery (status callbacks now, inbound messages in phase 5).

Every attempt is signed with X-Twilio-Signature and recorded in the
WebhookDelivery log, success or failure.
"""

import asyncio
import json
import random
import time
from datetime import UTC, datetime
from urllib.parse import urlencode

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
    method: str = "POST",
) -> WebhookDelivery:
    """Send signed params to url (form-encoded POST, or query-string GET);
    record the attempt in the log.

    Signature rules match Twilio: POST signs url + sorted key/value pairs;
    GET signs the full URL including the query string, with nothing appended.
    Chaos settings apply: artificial latency, injected failures, and retries
    after failed deliveries (each retry logged as its own attempt).
    """
    with Session(get_engine()) as session:
        settings = get_settings(session)
        auth_token = settings.auth_token
        latency = settings.webhook_latency_ms / 1000
        failure_rate = settings.webhook_failure_rate
        retries = settings.webhook_retry_count

    delivery = await _attempt(
        kind, url, params, message_sid, method, auth_token, latency, failure_rate
    )
    attempt = 0
    while attempt < retries and _failed(delivery):
        attempt += 1
        await asyncio.sleep(min(0.2 * attempt, 2.0))
        delivery = await _attempt(
            kind, url, params, message_sid, method, auth_token, latency, failure_rate
        )
    return delivery


def _failed(delivery: WebhookDelivery) -> bool:
    return delivery.error is not None or not (
        delivery.response_status is not None and 200 <= delivery.response_status < 300
    )


async def _attempt(
    kind: str,
    url: str,
    params: dict[str, str],
    message_sid: str | None,
    method: str,
    auth_token: str,
    latency: float,
    failure_rate: float,
) -> WebhookDelivery:
    method = (method or "POST").upper()
    if latency > 0:
        await asyncio.sleep(latency)

    started = time.monotonic()
    response_status: int | None = None
    response_body: str | None = None
    error: str | None = None
    if failure_rate > 0 and random.random() < failure_rate:
        error = "ChaosError: delivery dropped by webhook_failure_rate"
    else:
        try:
            async with httpx.AsyncClient(transport=_transport, timeout=10) as client:
                if method == "GET":
                    joiner = "&" if "?" in url else "?"
                    full_url = url + joiner + urlencode(params)
                    headers = {"X-Twilio-Signature": compute_signature(auth_token, full_url, {})}
                    response = await client.get(full_url, headers=headers)
                else:
                    headers = {"X-Twilio-Signature": compute_signature(auth_token, url, params)}
                    response = await client.post(url, data=params, headers=headers)
            response_status = response.status_code
            response_body = response.text[:RESPONSE_BODY_LIMIT]
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    delivery = WebhookDelivery(
        kind=kind,
        url=url,
        method=method,
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


def build_inbound_params(
    message: Message,
    media: list,
    public_base_url: str,
    geo_params: dict[str, str],
    optout_type: str | None,
) -> dict[str, str]:
    """Twilio inbound-message webhook params (SPEC §2.1)."""
    params = {
        "MessageSid": message.sid,
        "SmsSid": message.sid,
        "SmsMessageSid": message.sid,
        "AccountSid": message.account_sid,
        "From": message.from_number,
        "To": message.to_number,
        "Body": message.body,
        "NumMedia": str(message.num_media),
        "NumSegments": str(message.num_segments),
        "SmsStatus": "received",
        "ApiVersion": API_VERSION,
    }
    if message.messaging_service_sid:
        params["MessagingServiceSid"] = message.messaging_service_sid
    for index, item in enumerate(media):
        params[f"MediaUrl{index}"] = f"{public_base_url.rstrip('/')}/api/media/{item.sid}"
        params[f"MediaContentType{index}"] = item.content_type
    if optout_type is not None:
        params["OptOutType"] = optout_type
    params.update(geo_params)
    return params
