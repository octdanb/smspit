"""Opt-out keyword engine (STOP/START/HELP), mirroring Twilio's defaults.

Keyword lists and confirmation bodies are configurable via Settings.optout_config
(mirrors Twilio's Advanced Opt-Out).
"""

import json

from sqlmodel import Session, select

from .db import get_settings
from .models import DEFAULT_OPTOUT_CONFIG, OptOut, utcnow


def load_config(session: Session) -> dict:
    raw = get_settings(session).optout_config
    try:
        config = json.loads(raw) if raw else {}
    except ValueError:
        config = {}
    keywords = {**DEFAULT_OPTOUT_CONFIG["keywords"], **config.get("keywords", {})}
    confirmations = {**DEFAULT_OPTOUT_CONFIG["confirmations"], **config.get("confirmations", {})}
    return {"keywords": keywords, "confirmations": confirmations}


def match_keyword(body: str, config: dict) -> str | None:
    """Return 'STOP' | 'START' | 'HELP' when the body is an opt-out keyword."""
    normalized = body.strip().upper()
    for kind in ("stop", "start", "help"):
        if normalized in (k.upper() for k in config["keywords"].get(kind, [])):
            return kind.upper()
    return None


def _find_pair(session: Session, recipient: str, sender: str) -> OptOut | None:
    return session.exec(
        select(OptOut).where(OptOut.recipient == recipient, OptOut.sender == sender)
    ).first()


def set_opted_out(session: Session, recipient: str, sender: str, opted_out: bool) -> OptOut:
    if sender == "*":
        # A wildcard update overrides every sender-specific pair for this
        # recipient — otherwise "opt back in" wouldn't clear a STOP-created pair.
        for existing in session.exec(select(OptOut).where(OptOut.recipient == recipient)).all():
            existing.opted_out = opted_out
            existing.date_updated = utcnow()
            session.add(existing)
    pair = _find_pair(session, recipient, sender)
    if pair is None:
        pair = OptOut(recipient=recipient, sender=sender, opted_out=opted_out)
    else:
        pair.opted_out = opted_out
        pair.date_updated = utcnow()
    session.add(pair)
    session.commit()
    session.refresh(pair)
    return pair


def is_opted_out(session: Session, recipient: str, sender: str) -> bool:
    """True when (recipient, sender) — or a wildcard pair — is opted out."""
    pairs = session.exec(
        select(OptOut).where(
            OptOut.recipient == recipient,
            OptOut.opted_out == True,  # noqa: E712
        )
    ).all()
    return any(pair.sender in (sender, "*") for pair in pairs)


def has_any_optout(session: Session, recipient: str) -> bool:
    return (
        session.exec(
            select(OptOut).where(
                OptOut.recipient == recipient,
                OptOut.opted_out == True,  # noqa: E712
            )
        ).first()
        is not None
    )
