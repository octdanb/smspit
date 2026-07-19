"""Retention: auto-purge old messages (Mailpit-style), configurable in settings."""

import asyncio
from datetime import timedelta

from sqlmodel import Session, col, select

from . import tags
from .db import get_engine, get_settings
from .models import MediaItem, Message, utcnow
from .ws import manager

PURGE_INTERVAL_SECONDS = 60


def purge_once(session: Session) -> int:
    """Delete messages past the configured age/count limits. Returns count removed."""
    settings = get_settings(session)
    doomed: list[Message] = []

    if settings.retention_max_age_hours > 0:
        cutoff = utcnow() - timedelta(hours=settings.retention_max_age_hours)
        doomed.extend(session.exec(select(Message).where(col(Message.date_created) < cutoff)).all())

    if settings.retention_max_messages > 0:
        keepers = session.exec(
            select(Message.id)
            .order_by(col(Message.date_created).desc(), col(Message.id).desc())
            .limit(settings.retention_max_messages)
        ).all()
        if keepers:
            doomed.extend(
                session.exec(
                    select(Message).where(col(Message.id).not_in(keepers))  # type: ignore[union-attr]
                ).all()
            )

    unique = {message.sid: message for message in doomed}
    if not unique:
        return 0

    sids = list(unique.keys())
    tags.delete_tags_for_messages(session, sids)
    for item in session.exec(
        select(MediaItem).where(MediaItem.message_sid.in_(sids))  # type: ignore[attr-defined]
    ).all():
        session.delete(item)
    for message in unique.values():
        session.delete(message)
    session.commit()
    return len(unique)


async def purge_loop() -> None:
    while True:
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)
        try:
            with Session(get_engine()) as session:
                removed = purge_once(session)
            if removed:
                await manager.broadcast("messages.cleared", {"number": None})
        except Exception:
            pass  # never let the maintenance loop die
