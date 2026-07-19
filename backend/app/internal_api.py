"""Internal REST API used by the dashboard and test automation."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlmodel import Session, col, delete, func, or_, select

from . import inbound, media, optout, otp, webhooks
from .db import get_session, get_settings
from .models import MediaItem, Message, OptOut, Verification, VerifyService, WebhookDelivery, utcnow
from .ws import manager

router = APIRouter(prefix="/api")


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def message_to_internal(session: Session, message: Message) -> dict:
    media_items = media.media_for_message(session, message.sid) if message.num_media > 0 else []
    return {
        "sid": message.sid,
        "direction": message.direction,
        "from_number": message.from_number,
        "to_number": message.to_number,
        "body": message.body,
        "status": message.status,
        "error_code": message.error_code,
        "error_message": message.error_message,
        "num_segments": message.num_segments,
        "num_media": message.num_media,
        "encoding": message.encoding,
        "channel": message.channel,
        "media": [
            {"sid": item.sid, "content_type": item.content_type, "url": f"/api/media/{item.sid}"}
            for item in media_items
        ],
        "date_created": iso(message.date_created),
        "date_sent": iso(message.date_sent),
        "date_updated": iso(message.date_updated),
    }


def counterparty(message: Message) -> str:
    """The external number a message belongs to (the non-app side of the thread)."""
    return message.to_number if message.direction.startswith("outbound") else message.from_number


@router.get("/numbers")
def list_numbers(
    session: Session = Depends(get_session), q: str | None = Query(None)
) -> list[dict]:
    """All counterparty numbers with message counts and the latest message preview.

    ?q= searches numbers AND full message bodies (not just the preview).
    """
    messages = session.exec(
        select(Message).order_by(col(Message.date_created).asc(), col(Message.id).asc())
    ).all()

    opted_out_numbers = {
        pair.recipient
        for pair in session.exec(select(OptOut).where(OptOut.opted_out == True)).all()  # noqa: E712
    }

    query = (q or "").strip().lower()
    matching_numbers: set[str] = set()
    threads: dict[str, dict] = {}
    for message in messages:
        number = counterparty(message)
        if query and (query in number.lower() or query in message.body.lower()):
            matching_numbers.add(number)
        thread = threads.setdefault(
            number,
            {"number": number, "message_count": 0, "opted_out": number in opted_out_numbers},
        )
        thread["message_count"] += 1
        thread["last_message"] = {
            "sid": message.sid,
            "body": message.body,
            "direction": message.direction,
            "status": message.status,
            "date_created": iso(message.date_created),
        }

    results = threads.values()
    if query:
        results = [t for t in results if t["number"] in matching_numbers]
    return sorted(
        results,
        key=lambda t: t["last_message"]["date_created"],
        reverse=True,
    )


@router.get("/numbers/{number}/messages")
def thread_messages(
    number: str,
    session: Session = Depends(get_session),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """Conversation thread for a number, oldest first (chat order), paginated."""
    condition = or_(Message.to_number == number, Message.from_number == number)
    total = session.exec(select(func.count()).select_from(Message).where(condition)).one()
    messages = session.exec(
        select(Message)
        .where(condition)
        .order_by(col(Message.date_created).desc(), col(Message.id).desc())
        .offset(page * page_size)
        .limit(page_size)
    ).all()

    return {
        "number": number,
        "messages": [message_to_internal(session, m) for m in reversed(messages)],
        "opted_out": optout.has_any_optout(session, number),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/numbers/{number}/latest-code")
def latest_code(
    number: str,
    session: Session = Depends(get_session),
    regex: str | None = Query(None),
) -> dict:
    """Most recent OTP code sent TO this number — for E2E test automation."""
    messages = session.exec(
        select(Message)
        .where(Message.to_number == number)
        .order_by(col(Message.date_created).desc(), col(Message.id).desc())
        .limit(100)
    ).all()
    for message in messages:
        try:
            code = otp.extract_code(message.body, regex)
        except Exception as exc:  # invalid user-supplied regex
            raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc
        if code:
            age = int((utcnow() - message.date_created).total_seconds())
            return {
                "code": code,
                "message_sid": message.sid,
                "body": message.body,
                "date_created": iso(message.date_created),
                "age_seconds": age,
            }
    raise HTTPException(status_code=404, detail=f"No verification code found for {number}")


@router.get("/numbers/{number}/verifications")
def number_verifications(number: str, session: Session = Depends(get_session)) -> list[dict]:
    """Verify v2 verifications for a number (newest first), with expected codes."""
    verifications = session.exec(
        select(Verification)
        .where(Verification.to == number)
        .order_by(col(Verification.date_created).desc())
        .limit(20)
    ).all()
    services = {s.sid: s.friendly_name for s in session.exec(select(VerifyService)).all()}
    now = utcnow()
    return [
        {
            "sid": v.sid,
            "service_sid": v.service_sid,
            "service_name": services.get(v.service_sid, "?"),
            "status": v.status,
            "code": v.code,
            "check_attempts": v.check_attempts,
            "send_attempts": len(json.loads(v.send_attempts or "[]")),
            "expires_in_seconds": max(int((v.expires_at - now).total_seconds()), 0),
            "date_created": iso(v.date_created),
        }
        for v in verifications
    ]


class ReplyPayload(BaseModel):
    body: str
    to: str | None = None
    media_urls: list[str] = []
    geo: dict[str, str] | None = None


@router.post("/numbers/{number}/reply")
async def reply(
    number: str, payload: ReplyPayload, session: Session = Depends(get_session)
) -> dict:
    """Simulate an inbound SMS from this number (fires the inbound webhook)."""
    message = await inbound.handle_reply(
        session,
        number,
        body=payload.body,
        to=payload.to,
        media_urls=payload.media_urls,
        geo=payload.geo,
    )
    return message_to_internal(session, message)


@router.get("/media/{media_sid}")
async def media_content(media_sid: str, session: Session = Depends(get_session)) -> Response:
    """Serve MMS bytes (fetched lazily from the original MediaUrl)."""
    item = session.get(MediaItem, media_sid)
    if item is None:
        raise HTTPException(status_code=404, detail="Media not found")
    content, content_type = await media.fetch_content(session, item)
    return Response(content=content, media_type=content_type)


class OptOutUpdate(BaseModel):
    recipient: str
    sender: str = "*"
    opted_out: bool


@router.get("/optouts")
def list_optouts(session: Session = Depends(get_session)) -> list[dict]:
    pairs = session.exec(select(OptOut).order_by(col(OptOut.id).desc())).all()
    return [
        {
            "recipient": pair.recipient,
            "sender": pair.sender,
            "opted_out": pair.opted_out,
            "date_updated": iso(pair.date_updated),
        }
        for pair in pairs
    ]


@router.put("/optouts")
async def update_optout(payload: OptOutUpdate, session: Session = Depends(get_session)) -> dict:
    pair = optout.set_opted_out(session, payload.recipient, payload.sender, payload.opted_out)
    await manager.broadcast("optout.changed", {"number": payload.recipient})
    return {
        "recipient": pair.recipient,
        "sender": pair.sender,
        "opted_out": pair.opted_out,
    }


def settings_to_json(settings) -> dict:
    return {
        "inbound_webhook_url": settings.inbound_webhook_url,
        "inbound_webhook_method": settings.inbound_webhook_method,
        "account_sid": settings.account_sid,
        "auth_token": settings.auth_token,
        "simulate_delivery": settings.simulate_delivery,
        "status_delay_ms": settings.status_delay_ms,
        "failure_rate": settings.failure_rate,
        "forced_rules": json.loads(settings.forced_rules or "[]"),
        "public_base_url": settings.public_base_url,
        "enforce_optouts": settings.enforce_optouts,
        "optout_config": json.loads(settings.optout_config or "{}"),
        "webhook_geo_params": json.loads(settings.webhook_geo_params or "{}"),
        "verify_ttl_seconds": settings.verify_ttl_seconds,
        "lookup_line_types": json.loads(settings.lookup_line_types or "{}"),
        "strict_auth": settings.strict_auth,
        "strict_validation": settings.strict_validation,
        "trial_mode": settings.trial_mode,
        "verified_numbers": json.loads(settings.verified_numbers or "[]"),
        "rate_limit_per_minute": settings.rate_limit_per_minute,
    }


class ForcedRule(BaseModel):
    to_suffix: str
    status: str = "undelivered"  # undelivered | failed
    error_code: int = 30008


class SettingsUpdate(BaseModel):
    inbound_webhook_url: str | None = None
    inbound_webhook_method: str | None = None
    account_sid: str | None = None
    auth_token: str | None = None
    simulate_delivery: bool | None = None
    status_delay_ms: int | None = None
    failure_rate: float | None = None
    forced_rules: list[ForcedRule] | None = None
    public_base_url: str | None = None
    enforce_optouts: bool | None = None
    optout_config: dict | None = None
    webhook_geo_params: dict[str, str] | None = None
    verify_ttl_seconds: int | None = None
    lookup_line_types: dict[str, str] | None = None
    strict_auth: bool | None = None
    strict_validation: bool | None = None
    trial_mode: bool | None = None
    verified_numbers: list[str] | None = None
    rate_limit_per_minute: int | None = None


@router.get("/settings")
def read_settings(session: Session = Depends(get_session)) -> dict:
    return settings_to_json(get_settings(session))


@router.put("/settings")
def update_settings(payload: SettingsUpdate, session: Session = Depends(get_session)) -> dict:
    settings = get_settings(session)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in (
            "forced_rules",
            "optout_config",
            "webhook_geo_params",
            "lookup_line_types",
            "verified_numbers",
        ):
            setattr(settings, key, json.dumps(value))
        else:
            setattr(settings, key, value)
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings_to_json(settings)


def delivery_to_json(delivery: WebhookDelivery) -> dict:
    return {
        "id": delivery.id,
        "kind": delivery.kind,
        "url": delivery.url,
        "request_params": json.loads(delivery.request_params or "{}"),
        "response_status": delivery.response_status,
        "response_body": delivery.response_body,
        "duration_ms": delivery.duration_ms,
        "error": delivery.error,
        "message_sid": delivery.message_sid,
        "created_at": iso(delivery.created_at),
    }


@router.get("/webhook-log")
def webhook_log(
    session: Session = Depends(get_session),
    page: int = Query(0, ge=0),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    total = session.exec(select(func.count()).select_from(WebhookDelivery)).one()
    deliveries = session.exec(
        select(WebhookDelivery)
        .order_by(col(WebhookDelivery.id).desc())
        .offset(page * page_size)
        .limit(page_size)
    ).all()
    return {
        "deliveries": [delivery_to_json(d) for d in deliveries],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/webhook-log/{delivery_id}/retry")
async def retry_webhook(delivery_id: int, session: Session = Depends(get_session)) -> dict:
    delivery = session.get(WebhookDelivery, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    params = json.loads(delivery.request_params or "{}")
    new_delivery = await webhooks.deliver(delivery.kind, delivery.url, params, delivery.message_sid)
    return delivery_to_json(new_delivery)


@router.delete("/messages", status_code=204)
async def clear_all_messages(session: Session = Depends(get_session)) -> None:
    session.exec(delete(Message))
    session.commit()
    await manager.broadcast("messages.cleared", {"number": None})


@router.delete("/numbers/{number}/messages", status_code=204)
async def clear_thread(number: str, session: Session = Depends(get_session)) -> None:
    session.exec(
        delete(Message).where(
            or_(col(Message.to_number) == number, col(Message.from_number) == number)
        )
    )
    session.commit()
    await manager.broadcast("messages.cleared", {"number": number})
