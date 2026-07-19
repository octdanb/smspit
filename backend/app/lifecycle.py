"""Delivery lifecycle simulation.

Advances messages through Twilio's status chain with configurable delays:

    direct:    queued -> sending -> sent -> delivered | undelivered
    scheduled: scheduled -> queued -> ... (waits until send_at)
    rejected:  queued -> failed (forced rules; never reaches the carrier)

Each transition persists, broadcasts message.status_changed, and fires the
StatusCallback webhook. Failure outcomes come from forced per-number rules
(deterministic, for tests) or a global random failure rate.
"""

import asyncio
import json
import random

from sqlmodel import Session, select

from . import webhooks
from .db import get_engine, get_settings
from .models import Message, utcnow
from .ws import manager

TERMINAL_STATUSES = {"delivered", "undelivered", "failed", "received", "canceled"}
CALLBACK_STATUSES = {"queued", "sending", "sent", "delivered", "undelivered", "failed"}
PRICE_PER_SEGMENT = 0.0075

ERROR_MESSAGES = {
    30003: "Unreachable destination handset",
    30004: "Message blocked",
    30005: "Unknown destination handset",
    30006: "Landline or unreachable carrier",
    30007: "Message filtered",
    30008: "Unknown error",
}


def start(sid: str) -> None:
    """Kick off (or resume) lifecycle simulation for a message."""
    asyncio.get_running_loop().create_task(_run(sid))


def resume_pending() -> None:
    """Re-arm simulation for non-terminal messages after a restart."""
    with Session(get_engine()) as session:
        if not get_settings(session).simulate_delivery:
            return
        pending = session.exec(
            select(Message.sid).where(
                Message.status.in_(("scheduled", "queued", "sending", "sent"))  # type: ignore[attr-defined]
            )
        ).all()
    for sid in pending:
        start(sid)


def _forced_rule(message: Message, forced_rules: list[dict]) -> dict | None:
    for rule in forced_rules:
        suffix = str(rule.get("to_suffix", ""))
        if suffix and message.to_number.endswith(suffix):
            return rule
    return None


def _next_transition(
    message: Message, forced_rules: list[dict], failure_rate: float
) -> tuple[str, int | None] | None:
    """(next_status, error_code) for one step of the chain, or None when done."""
    if message.status == "scheduled":
        return "queued", None
    if message.status == "queued":
        rule = _forced_rule(message, forced_rules)
        if rule is not None and rule.get("status") == "failed":
            return "failed", int(rule.get("error_code", 30008))
        return "sending", None
    if message.status == "sending":
        return "sent", None
    if message.status == "sent":
        rule = _forced_rule(message, forced_rules)
        if rule is not None and rule.get("status") == "undelivered":
            return "undelivered", int(rule.get("error_code", 30008))
        if failure_rate > 0 and random.random() < failure_rate:
            return "undelivered", 30008
        return "delivered", None
    return None


async def _run(sid: str) -> None:
    while True:
        with Session(get_engine()) as session:
            message = session.exec(select(Message).where(Message.sid == sid)).first()
            if message is None or message.status in TERMINAL_STATUSES:
                return
            settings = get_settings(session)
            forced_rules = json.loads(settings.forced_rules or "[]")
            delay = settings.status_delay_ms / 1000

        if message.status == "scheduled":
            if message.send_at is not None:
                wait = (message.send_at - utcnow()).total_seconds()
                if wait > 0:
                    await asyncio.sleep(wait)
        else:
            await asyncio.sleep(delay)

        step = _next_transition(message, forced_rules, settings.failure_rate)
        if step is None:
            return
        next_status, error_code = step
        if not await _apply_transition(sid, message.status, next_status, error_code):
            return


async def _apply_transition(
    sid: str, expected_current: str, next_status: str, error_code: int | None
) -> bool:
    """Atomically move a message to next_status; returns False if it changed under us."""
    with Session(get_engine()) as session:
        message = session.exec(select(Message).where(Message.sid == sid)).first()
        if message is None or message.status != expected_current:
            # Canceled or mutated externally while we slept — stop simulating.
            return False

        message.status = next_status
        message.date_updated = utcnow()
        if next_status == "sent":
            message.date_sent = utcnow()
            message.price = f"-{PRICE_PER_SEGMENT * message.num_segments:.5f}"
        if next_status in ("undelivered", "failed"):
            message.error_code = error_code or 30008
            message.error_message = ERROR_MESSAGES.get(message.error_code, "Unknown error")
        session.add(message)
        session.commit()
        session.refresh(message)

        from .internal_api import counterparty, message_to_internal

        payload = {
            "number": counterparty(message),
            "message": message_to_internal(session, message),
        }
        callback_message = message

    await manager.broadcast("message.status_changed", payload)
    if next_status in CALLBACK_STATUSES:
        await webhooks.deliver_status_callback(callback_message, next_status)
    return True
