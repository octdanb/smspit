"""Internal REST API used by the dashboard and test automation."""

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, col, delete, func, or_, select

from . import webhooks
from .db import get_session, get_settings
from .models import Message, WebhookDelivery
from .ws import manager

router = APIRouter(prefix="/api")


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def message_to_internal(message: Message) -> dict:
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
        "date_created": iso(message.date_created),
        "date_sent": iso(message.date_sent),
        "date_updated": iso(message.date_updated),
    }


def counterparty(message: Message) -> str:
    """The external number a message belongs to (the non-app side of the thread)."""
    return message.to_number if message.direction.startswith("outbound") else message.from_number


@router.get("/numbers")
def list_numbers(session: Session = Depends(get_session)) -> list[dict]:
    """All counterparty numbers with message counts and the latest message preview."""
    messages = session.exec(
        select(Message).order_by(col(Message.date_created).asc(), col(Message.id).asc())
    ).all()

    threads: dict[str, dict] = {}
    for message in messages:
        number = counterparty(message)
        thread = threads.setdefault(number, {"number": number, "message_count": 0})
        thread["message_count"] += 1
        thread["last_message"] = {
            "sid": message.sid,
            "body": message.body,
            "direction": message.direction,
            "status": message.status,
            "date_created": iso(message.date_created),
        }

    return sorted(
        threads.values(),
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
        "messages": [message_to_internal(m) for m in reversed(messages)],
        "total": total,
        "page": page,
        "page_size": page_size,
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


@router.get("/settings")
def read_settings(session: Session = Depends(get_session)) -> dict:
    return settings_to_json(get_settings(session))


@router.put("/settings")
def update_settings(payload: SettingsUpdate, session: Session = Depends(get_session)) -> dict:
    settings = get_settings(session)
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key == "forced_rules":
            settings.forced_rules = json.dumps(value)
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
