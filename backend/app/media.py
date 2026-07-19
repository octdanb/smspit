"""MMS media handling: lazy content fetch with a placeholder fallback."""

import base64
import mimetypes
import secrets

import httpx
from sqlmodel import Session, select

from .models import MediaItem, utcnow

# Tests inject an httpx.MockTransport here to serve media bytes.
_transport: httpx.AsyncBaseTransport | None = None

# 1x1 transparent PNG, served when the original MediaUrl is unreachable.
PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)

MAX_MEDIA_BYTES = 5 * 1024 * 1024  # Twilio's supported-media cap


def new_media_sid() -> str:
    return "ME" + secrets.token_hex(16)


def guess_content_type(url: str) -> str:
    guessed, _ = mimetypes.guess_type(url.split("?")[0])
    return guessed or "application/octet-stream"


def create_media_items(
    session: Session, message_sid: str, account_sid: str, urls: list[str]
) -> list[MediaItem]:
    items = [
        MediaItem(
            sid=new_media_sid(),
            message_sid=message_sid,
            account_sid=account_sid,
            content_type=guess_content_type(url),
            source_url=url,
        )
        for url in urls
    ]
    for item in items:
        session.add(item)
    session.commit()
    for item in items:
        session.refresh(item)
    return items


def media_for_message(session: Session, message_sid: str) -> list[MediaItem]:
    return list(
        session.exec(
            select(MediaItem).where(MediaItem.message_sid == message_sid).order_by(MediaItem.sid)
        ).all()
    )


async def fetch_content(session: Session, item: MediaItem) -> tuple[bytes, str]:
    """Return (bytes, content_type), downloading and caching on first access."""
    if item.content is not None:
        return item.content, item.content_type
    if item.source_url:
        try:
            async with httpx.AsyncClient(
                transport=_transport, timeout=10, follow_redirects=True
            ) as client:
                response = await client.get(item.source_url)
            response.raise_for_status()
            content = response.content[:MAX_MEDIA_BYTES]
            item.content = content
            item.content_type = response.headers.get("content-type", item.content_type).split(";")[
                0
            ]
            item.date_updated = utcnow()
            session.add(item)
            session.commit()
            session.refresh(item)
            return content, item.content_type
        except Exception:
            pass  # unreachable source: fall through to the placeholder
    return PLACEHOLDER_PNG, "image/png"
