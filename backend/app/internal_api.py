"""Internal REST API used by the dashboard and test automation."""

import csv
import io
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import Response as FastAPIResponse
from pydantic import BaseModel
from sqlmodel import Session, col, delete, func, or_, select

from . import inbound, media, optout, otp, tags, webhooks
from .db import get_session, get_settings
from .models import (
    MediaItem,
    Message,
    OptOut,
    ThreadRead,
    Verification,
    VerifyService,
    WebhookDelivery,
    utcnow,
)
from .ws import manager

router = APIRouter(prefix="/api")


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def message_to_internal(session: Session, message: Message) -> dict:
    media_items = media.media_for_message(session, message.sid) if message.num_media > 0 else []
    return {
        "tags": tags.tags_for(session, message.sid),
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

    # `tag:foo` tokens in the query filter by tag; remaining text searches
    # numbers and full message bodies.
    raw_query = (q or "").strip().lower()
    tag_filters = {
        token.removeprefix("tag:") for token in raw_query.split() if token.startswith("tag:")
    }
    query = " ".join(t for t in raw_query.split() if not t.startswith("tag:"))

    message_tags = tags.tags_for_many(session, [m.sid for m in messages])
    read_marks = {row.number: row.last_read_at for row in session.exec(select(ThreadRead)).all()}

    matching_numbers: set[str] = set()
    threads: dict[str, dict] = {}
    for message in messages:
        number = counterparty(message)
        if query and (query in number.lower() or query in message.body.lower()):
            matching_numbers.add(number)
        thread = threads.setdefault(
            number,
            {
                "number": number,
                "message_count": 0,
                "unread_count": 0,
                "opted_out": number in opted_out_numbers,
                "tags": set(),
            },
        )
        thread["message_count"] += 1
        thread["tags"].update(message_tags.get(message.sid, []))
        last_read = read_marks.get(number)
        if last_read is None or message.date_created > last_read:
            thread["unread_count"] += 1
        thread["last_message"] = {
            "sid": message.sid,
            "body": message.body,
            "direction": message.direction,
            "status": message.status,
            "date_created": iso(message.date_created),
        }

    results = list(threads.values())
    if query:
        results = [t for t in results if t["number"] in matching_numbers]
    if tag_filters:
        results = [
            t for t in results if all(tag in {x.lower() for x in t["tags"]} for tag in tag_filters)
        ]
    for thread in results:
        thread["tags"] = sorted(thread["tags"])
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


@router.post("/numbers/{number}/read", status_code=204)
def mark_thread_read(number: str, session: Session = Depends(get_session)) -> None:
    mark = session.get(ThreadRead, number)
    if mark is None:
        mark = ThreadRead(number=number)
    mark.last_read_at = utcnow()
    session.add(mark)
    session.commit()


@router.get("/tags")
def list_tags(session: Session = Depends(get_session)) -> list[dict]:
    return tags.all_tags(session)


class TagsUpdate(BaseModel):
    tags: list[str]


@router.put("/messages/{sid}/tags")
async def update_message_tags(
    sid: str, payload: TagsUpdate, session: Session = Depends(get_session)
) -> dict:
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    updated = tags.set_tags(session, sid, payload.tags)
    await manager.broadcast(
        "tags.changed", {"number": counterparty(message), "tags": updated, "sid": sid}
    )
    return {"sid": sid, "tags": updated}


@router.get("/messages/{sid}")
def message_detail(sid: str, session: Session = Depends(get_session)) -> dict:
    """Everything the detail drawer needs: internal + Twilio shape + raw params."""
    from .twilio_api import message_to_json

    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return {
        "message": message_to_internal(session, message),
        "twilio": message_to_json(message),
        "raw_params": json.loads(message.raw_params or "{}"),
    }


@router.delete("/messages/{sid}", status_code=204)
async def delete_single_message(sid: str, session: Session = Depends(get_session)) -> None:
    """Dashboard delete: unlike the Twilio endpoint, works in any status."""
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    number = counterparty(message)
    tags.delete_tags_for_messages(session, [sid])
    for item in media.media_for_message(session, sid):
        session.delete(item)
    session.delete(message)
    session.commit()
    await manager.broadcast("messages.cleared", {"number": number})


EXPORT_COLUMNS = (
    "sid",
    "direction",
    "from_number",
    "to_number",
    "body",
    "status",
    "error_code",
    "num_segments",
    "num_media",
    "channel",
    "tags",
    "date_created",
    "date_sent",
)


@router.get("/export")
def export_messages(
    session: Session = Depends(get_session),
    format: str = Query("json", pattern="^(json|csv)$"),
    number: str | None = Query(None),
) -> FastAPIResponse:
    """Download all messages (or one thread) as JSON or CSV."""
    stmt = select(Message).order_by(col(Message.date_created).asc(), col(Message.id).asc())
    if number:
        stmt = stmt.where(or_(Message.to_number == number, Message.from_number == number))
    rows = [message_to_internal(session, m) for m in session.exec(stmt).all()]

    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    name = f"smspit-{number or 'all'}-{stamp}".replace("+", "")
    if format == "json":
        return FastAPIResponse(
            content=json.dumps(rows, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(EXPORT_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                ",".join(row[column]) if column == "tags" else row[column]
                for column in EXPORT_COLUMNS
            ]
        )
    return FastAPIResponse(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@router.get("/scheduled")
def list_scheduled(session: Session = Depends(get_session)) -> list[dict]:
    messages = session.exec(
        select(Message).where(Message.status == "scheduled").order_by(col(Message.send_at).asc())
    ).all()
    return [message_to_internal(session, m) | {"send_at": iso(m.send_at)} for m in messages]


@router.post("/scheduled/{sid}/cancel")
async def cancel_scheduled(sid: str, session: Session = Depends(get_session)) -> dict:
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None or message.status != "scheduled":
        raise HTTPException(status_code=404, detail="No scheduled message with that sid")
    message.status = "canceled"
    message.date_updated = utcnow()
    session.add(message)
    session.commit()
    session.refresh(message)
    await manager.broadcast(
        "message.status_changed",
        {"number": counterparty(message), "message": message_to_internal(session, message)},
    )
    return message_to_internal(session, message)


class SeedMessage(BaseModel):
    from_number: str
    to_number: str
    body: str
    direction: str = "outbound-api"  # outbound-api | inbound
    tags: list[str] = []


class SeedPayload(BaseModel):
    messages: list[SeedMessage] | None = None  # omit for the demo preset


DEMO_SEED = [
    SeedMessage(
        from_number="+15550100001",
        to_number="+15551230001",
        body="Welcome to smspit! Your verification code is 482913",
        tags=["otp"],
    ),
    SeedMessage(
        from_number="+15551230001",
        to_number="+15550100001",
        body="Thanks, signed up!",
        direction="inbound",
    ),
    SeedMessage(
        from_number="+15550100001",
        to_number="+15551230002",
        body="Spring sale starts tomorrow — 20% off everything.",
        tags=["campaign:spring"],
    ),
    SeedMessage(
        from_number="+15551230002",
        to_number="+15550100001",
        body="STOP",
        direction="inbound",
    ),
    SeedMessage(
        from_number="+15550100001",
        to_number="+15551230003",
        body="Your parcel is out for delivery 📦",
        tags=["shipping"],
    ),
]


@router.post("/seed", status_code=201)
async def seed(payload: SeedPayload | None = None, session: Session = Depends(get_session)) -> dict:
    """Load fixture data (demo preset by default) for screenshots and demos.

    Seeded messages skip lifecycle simulation and webhooks: outbound arrive
    as delivered, inbound as received.
    """
    seeds = (payload.messages if payload and payload.messages else None) or DEMO_SEED
    created = []
    for seed_message in seeds:
        message = await inbound.record_message(
            session,
            account_sid=get_settings(session).account_sid,
            direction=seed_message.direction,
            from_number=seed_message.from_number,
            to_number=seed_message.to_number,
            body=seed_message.body,
            status="received" if seed_message.direction == "inbound" else "delivered",
        )
        if seed_message.direction != "inbound":
            message.date_sent = message.date_created
            message.price = f"-{0.0075 * message.num_segments:.5f}"
            session.add(message)
            session.commit()
        if seed_message.tags:
            tags.set_tags(session, message.sid, seed_message.tags)
        created.append(message.sid)
    await manager.broadcast("messages.cleared", {"number": None})  # full refresh
    return {"created": len(created), "sids": created}


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
        "api_key_sid": settings.api_key_sid,
        "api_key_secret": settings.api_key_secret,
        "strict_validation": settings.strict_validation,
        "trial_mode": settings.trial_mode,
        "verified_numbers": json.loads(settings.verified_numbers or "[]"),
        "rate_limit_per_minute": settings.rate_limit_per_minute,
        "auto_tag_rules": json.loads(settings.auto_tag_rules or "[]"),
        "retention_max_age_hours": settings.retention_max_age_hours,
        "retention_max_messages": settings.retention_max_messages,
        "webhook_latency_ms": settings.webhook_latency_ms,
        "webhook_failure_rate": settings.webhook_failure_rate,
        "webhook_retry_count": settings.webhook_retry_count,
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
    api_key_sid: str | None = None
    api_key_secret: str | None = None
    strict_validation: bool | None = None
    trial_mode: bool | None = None
    verified_numbers: list[str] | None = None
    rate_limit_per_minute: int | None = None
    auto_tag_rules: list[dict] | None = None
    retention_max_age_hours: int | None = None
    retention_max_messages: int | None = None
    webhook_latency_ms: int | None = None
    webhook_failure_rate: float | None = None
    webhook_retry_count: int | None = None


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
            "auto_tag_rules",
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
        "method": delivery.method,
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
    kind: str | None = Query(None),
    message_sid: str | None = Query(None),
    result: str | None = Query(None, pattern="^(success|error)$"),
) -> dict:
    conditions = []
    if kind:
        conditions.append(WebhookDelivery.kind == kind)
    if message_sid:
        conditions.append(WebhookDelivery.message_sid == message_sid)
    if result == "success":
        conditions.append(col(WebhookDelivery.response_status).between(200, 299))
    elif result == "error":
        conditions.append(
            or_(
                col(WebhookDelivery.error).is_not(None),
                col(WebhookDelivery.response_status) < 200,
                col(WebhookDelivery.response_status) >= 300,
            )
        )

    count_stmt = select(func.count()).select_from(WebhookDelivery)
    list_stmt = select(WebhookDelivery)
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)

    total = session.exec(count_stmt).one()
    deliveries = session.exec(
        list_stmt.order_by(col(WebhookDelivery.id).desc()).offset(page * page_size).limit(page_size)
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
    new_delivery = await webhooks.deliver(
        delivery.kind, delivery.url, params, delivery.message_sid, method=delivery.method
    )
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
