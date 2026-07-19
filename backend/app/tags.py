"""Message tags (Mailpit-style): manual tags, auto-tag rules, and the Twilio
Tags send parameter surfaced as key:value tags."""

import json
import re

from sqlmodel import Session, func, select

from .db import get_settings
from .models import Message, MessageTag


def tags_for(session: Session, message_sid: str) -> list[str]:
    return sorted(
        session.exec(select(MessageTag.tag).where(MessageTag.message_sid == message_sid)).all()
    )


def tags_for_many(session: Session, sids: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {sid: [] for sid in sids}
    if not sids:
        return result
    rows = session.exec(
        select(MessageTag).where(MessageTag.message_sid.in_(sids))  # type: ignore[attr-defined]
    ).all()
    for row in rows:
        result.setdefault(row.message_sid, []).append(row.tag)
    return {sid: sorted(tags) for sid, tags in result.items()}


def set_tags(session: Session, message_sid: str, tags: list[str]) -> list[str]:
    """Replace a message's tag set."""
    for row in session.exec(select(MessageTag).where(MessageTag.message_sid == message_sid)).all():
        session.delete(row)
    cleaned = sorted({tag.strip() for tag in tags if tag.strip()})
    for tag in cleaned:
        session.add(MessageTag(message_sid=message_sid, tag=tag))
    session.commit()
    return cleaned


def _add_tags(session: Session, message_sid: str, new_tags: set[str]) -> None:
    existing = set(tags_for(session, message_sid))
    for tag in sorted(new_tags - existing):
        session.add(MessageTag(message_sid=message_sid, tag=tag))
    session.commit()


def apply_auto_tags(session: Session, message: Message, raw_params: dict | None = None) -> None:
    """Tag a new message: Twilio's Tags param (key:value) + configured rules."""
    new_tags: set[str] = set()

    raw_tags = (raw_params or {}).get("Tags")
    if raw_tags:
        try:
            parsed = json.loads(raw_tags if isinstance(raw_tags, str) else raw_tags[-1])
            if isinstance(parsed, dict):
                new_tags.update(f"{key}:{value}" for key, value in parsed.items())
        except ValueError:
            pass

    try:
        rules = json.loads(get_settings(session).auto_tag_rules or "[]")
    except ValueError:
        rules = []
    for rule in rules:
        tag = str(rule.get("tag") or "").strip()
        if not tag:
            continue
        to_suffix = str(rule.get("to_suffix") or "")
        from_suffix = str(rule.get("from_suffix") or "")
        body_regex = str(rule.get("body_regex") or "")
        if to_suffix and not message.to_number.endswith(to_suffix):
            continue
        if from_suffix and not message.from_number.endswith(from_suffix):
            continue
        if body_regex:
            try:
                if not re.search(body_regex, message.body):
                    continue
            except re.error:
                continue
        new_tags.add(tag)

    if new_tags:
        _add_tags(session, message.sid, new_tags)


def all_tags(session: Session) -> list[dict]:
    rows = session.exec(
        select(MessageTag.tag, func.count()).group_by(MessageTag.tag).order_by(MessageTag.tag)  # type: ignore[arg-type]
    ).all()
    return [{"tag": tag, "count": count} for tag, count in rows]


def delete_tags_for_messages(session: Session, sids: list[str]) -> None:
    if not sids:
        return
    for row in session.exec(
        select(MessageTag).where(MessageTag.message_sid.in_(sids))  # type: ignore[attr-defined]
    ).all():
        session.delete(row)
