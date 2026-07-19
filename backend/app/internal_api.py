"""Internal REST API used by the dashboard and test automation."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, col, delete, func, or_, select

from .db import get_session
from .models import Message

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


@router.delete("/messages", status_code=204)
def clear_all_messages(session: Session = Depends(get_session)) -> None:
    session.exec(delete(Message))
    session.commit()


@router.delete("/numbers/{number}/messages", status_code=204)
def clear_thread(number: str, session: Session = Depends(get_session)) -> None:
    session.exec(
        delete(Message).where(
            or_(col(Message.to_number) == number, col(Message.from_number) == number)
        )
    )
    session.commit()
