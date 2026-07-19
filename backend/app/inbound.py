"""Simulated inbound messages (dashboard replies) and the webhook round-trip.

A reply from a number:
1. records an inbound message (status=received),
2. runs the opt-out keyword engine (STOP/START/HELP + confirmation auto-reply),
3. delivers the Twilio-format inbound webhook to the configured URL,
4. parses a TwiML response into outbound auto-replies (following one Redirect).
"""

import asyncio
import json
import secrets

from fastapi import HTTPException
from sqlmodel import Session, col, select

from . import lifecycle, media, optout, tags, webhooks
from .db import get_settings
from .models import IncomingPhoneNumber, Message, MessagingService, WebhookDelivery
from .segments import segment_count
from .twiml import looks_like_twiml, parse_twiml
from .ws import manager


async def record_message(
    session: Session,
    *,
    account_sid: str,
    direction: str,
    from_number: str,
    to_number: str,
    body: str,
    media_urls: list[str] | None = None,
    status: str,
    messaging_service_sid: str | None = None,
) -> Message:
    """Create a message + its media items and broadcast message.created."""
    media_urls = media_urls or []
    encoding, num_segments = segment_count(body)
    is_mms = bool(media_urls)
    message = Message(
        sid=("MM" if is_mms else "SM") + secrets.token_hex(16),
        account_sid=account_sid,
        direction=direction,
        from_number=from_number,
        to_number=to_number,
        body=body,
        status=status,
        messaging_service_sid=messaging_service_sid,
        num_segments=num_segments,
        num_media=len(media_urls),
        encoding=encoding,
        channel="mms" if is_mms else ("whatsapp" if to_number.startswith("whatsapp:") else "sms"),
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    media.create_media_items(session, message.sid, account_sid, media_urls)
    tags.apply_auto_tags(session, message)

    from .internal_api import counterparty, message_to_internal

    capture_payload = {
        "number": counterparty(message),
        "message": message_to_internal(session, message),
    }
    await manager.broadcast("message.created", capture_payload)
    asyncio.get_running_loop().create_task(webhooks.deliver_capture(capture_payload))
    return message


async def send_auto_reply(
    session: Session, *, from_number: str, to_number: str, body: str, media_urls=None
) -> Message:
    """Record an app->user auto-reply (opt-out confirmation or TwiML <Message>)."""
    settings = get_settings(session)
    message = await record_message(
        session,
        account_sid=settings.account_sid,
        direction="outbound-reply",
        from_number=from_number,
        to_number=to_number,
        body=body,
        media_urls=media_urls,
        status="queued",
    )
    if settings.simulate_delivery:
        lifecycle.start(message.sid)
    return message


def infer_app_number(session: Session, number: str) -> str | None:
    """The app-side number for a thread: taken from its most recent message."""
    latest = session.exec(
        select(Message)
        .where((Message.to_number == number) | (Message.from_number == number))
        .order_by(col(Message.date_created).desc(), col(Message.id).desc())
    ).first()
    if latest is None:
        return None
    return latest.from_number if latest.to_number == number else latest.to_number


def service_for_thread(session: Session, number: str) -> MessagingService | None:
    """The Messaging Service that last messaged this number, if any."""
    latest = session.exec(
        select(Message)
        .where(
            Message.to_number == number,
            col(Message.messaging_service_sid).is_not(None),
            col(Message.direction).startswith("outbound"),
        )
        .order_by(col(Message.date_created).desc(), col(Message.id).desc())
    ).first()
    if latest is None:
        return None
    return session.get(MessagingService, latest.messaging_service_sid)


async def _handle_twiml_response(
    session: Session, delivery: WebhookDelivery, user_number: str, app_number: str
) -> None:
    """Turn a TwiML webhook response into outbound auto-replies (one Redirect hop)."""
    body = delivery.response_body or ""
    status = delivery.response_status
    if status is None or not (200 <= status < 300) or not looks_like_twiml("", body):
        return
    try:
        result = parse_twiml(body)
    except ValueError:
        return  # malformed TwiML: already visible in the webhook log

    for twiml_message in result.messages:
        if not twiml_message.body and not twiml_message.media:
            continue
        await send_auto_reply(
            session,
            from_number=twiml_message.from_ or app_number,
            to_number=twiml_message.to or user_number,
            body=twiml_message.body,
            media_urls=twiml_message.media,
        )

    if result.redirect_url:
        params = json.loads(delivery.request_params or "{}")
        redirected = await webhooks.deliver(
            "inbound", result.redirect_url, params, delivery.message_sid
        )
        redirect_body = redirected.response_body or ""
        if (
            redirected.response_status
            and 200 <= redirected.response_status < 300
            and looks_like_twiml("", redirect_body)
        ):
            try:
                nested = parse_twiml(redirect_body)
            except ValueError:
                return
            for twiml_message in nested.messages:
                if not twiml_message.body and not twiml_message.media:
                    continue
                await send_auto_reply(
                    session,
                    from_number=twiml_message.from_ or app_number,
                    to_number=twiml_message.to or user_number,
                    body=twiml_message.body,
                    media_urls=twiml_message.media,
                )


async def handle_reply(
    session: Session,
    number: str,
    *,
    body: str,
    to: str | None = None,
    media_urls: list[str] | None = None,
    geo: dict[str, str] | None = None,
) -> Message:
    settings = get_settings(session)
    app_number = to or infer_app_number(session, number)
    if not app_number:
        raise HTTPException(
            status_code=400,
            detail="No app number known for this thread yet; provide 'to' explicitly.",
        )

    config = optout.load_config(session)
    optout_type = optout.match_keyword(body, config)

    # Webhook routing precedence (mirrors Twilio): Messaging Service
    # InboundRequestUrl (unless UseInboundWebhookOnNumber) > the receiving
    # number's SmsUrl (IncomingPhoneNumbers config) > the global settings URL.
    service = service_for_thread(session, number)
    number_config = session.exec(
        select(IncomingPhoneNumber).where(IncomingPhoneNumber.phone_number == app_number)
    ).first()

    webhook_url = settings.inbound_webhook_url
    webhook_method = settings.inbound_webhook_method
    fallback_url: str | None = None
    fallback_method = "POST"
    if number_config is not None and number_config.sms_url:
        webhook_url = number_config.sms_url
        webhook_method = number_config.sms_method
        fallback_url = number_config.sms_fallback_url
        fallback_method = number_config.sms_fallback_method
    if (
        service is not None
        and service.inbound_request_url
        and not service.use_inbound_webhook_on_number
    ):
        webhook_url = service.inbound_request_url
        webhook_method = service.inbound_method
        fallback_url = service.fallback_url
        fallback_method = service.fallback_method

    message = await record_message(
        session,
        account_sid=settings.account_sid,
        direction="inbound",
        from_number=number,
        to_number=app_number,
        body=body,
        media_urls=media_urls,
        status="received",
        messaging_service_sid=service.sid if service is not None else None,
    )

    if optout_type == "STOP":
        optout.set_opted_out(session, number, app_number, True)
        await manager.broadcast("optout.changed", {"number": number})
        await send_auto_reply(
            session,
            from_number=app_number,
            to_number=number,
            body=config["confirmations"]["stop"],
        )
    elif optout_type == "START":
        optout.set_opted_out(session, number, app_number, False)
        await manager.broadcast("optout.changed", {"number": number})
        await send_auto_reply(
            session,
            from_number=app_number,
            to_number=number,
            body=config["confirmations"]["start"],
        )
    elif optout_type == "HELP":
        await send_auto_reply(
            session,
            from_number=app_number,
            to_number=number,
            body=config["confirmations"]["help"],
        )

    if webhook_url:
        geo_params = {}
        try:
            geo_params.update(json.loads(settings.webhook_geo_params or "{}"))
        except ValueError:
            pass
        geo_params.update(geo or {})
        params = webhooks.build_inbound_params(
            message,
            media.media_for_message(session, message.sid),
            settings.public_base_url,
            geo_params,
            optout_type,
        )
        delivery = await webhooks.deliver(
            "inbound", webhook_url, params, message.sid, method=webhook_method
        )
        failed = delivery.error is not None or not (
            delivery.response_status is not None and 200 <= delivery.response_status < 300
        )
        if failed and fallback_url:
            # Twilio calls the fallback URL when the primary handler errors.
            delivery = await webhooks.deliver(
                "inbound", fallback_url, params, message.sid, method=fallback_method
            )
        await _handle_twiml_response(session, delivery, number, app_number)

    return message
