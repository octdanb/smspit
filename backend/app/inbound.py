"""Simulated inbound messages (dashboard replies) and the webhook round-trip.

A reply from a number:
1. records an inbound message (status=received),
2. runs the opt-out keyword engine (STOP/START/HELP + confirmation auto-reply),
3. delivers the Twilio-format inbound webhook to the configured URL,
4. parses a TwiML response into outbound auto-replies (following one Redirect).
"""

import json
import secrets

from fastapi import HTTPException
from sqlmodel import Session, col, select

from . import lifecycle, media, optout, webhooks
from .db import get_settings
from .models import Message, WebhookDelivery
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
        num_segments=num_segments,
        num_media=len(media_urls),
        encoding=encoding,
        channel="mms" if is_mms else ("whatsapp" if to_number.startswith("whatsapp:") else "sms"),
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    media.create_media_items(session, message.sid, account_sid, media_urls)

    from .internal_api import counterparty, message_to_internal

    await manager.broadcast(
        "message.created",
        {"number": counterparty(message), "message": message_to_internal(session, message)},
    )
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

    message = await record_message(
        session,
        account_sid=settings.account_sid,
        direction="inbound",
        from_number=number,
        to_number=app_number,
        body=body,
        media_urls=media_urls,
        status="received",
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

    if settings.inbound_webhook_url:
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
            "inbound", settings.inbound_webhook_url, params, message.sid
        )
        await _handle_twiml_response(session, delivery, number, app_number)

    return message
