"""MMS media handling: lazy content fetch with a placeholder fallback."""

import base64
import ipaddress
import mimetypes
import secrets
import socket
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from .config import config
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


def _is_fetchable(url: str) -> bool:
    """SSRF guard: only http(s), and (unless explicitly allowed) never a host
    that resolves to a private/loopback/link-local/reserved address."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    if config.allow_private_media:
        return True
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 0, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return False
    return True


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


async def _download(url: str) -> tuple[bytes, str] | None:
    """Fetch a URL with redirects disabled and a hard size cap, streaming so an
    oversized/hostile body can't be buffered whole into memory. None on failure."""
    if _transport is None and not _is_fetchable(url):
        return None  # SSRF guard (bypassed for the test transport)
    try:
        async with httpx.AsyncClient(
            transport=_transport, timeout=10, follow_redirects=False
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                declared = response.headers.get("content-length")
                if declared is not None and int(declared) > MAX_MEDIA_BYTES:
                    return None
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_MEDIA_BYTES:
                        return None
                    chunks.append(chunk)
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                return b"".join(chunks), content_type or "application/octet-stream"
    except Exception:
        return None


async def fetch_content(session: Session, item: MediaItem) -> tuple[bytes, str]:
    """Return (bytes, content_type), downloading and caching on first access."""
    if item.content is not None:
        return item.content, item.content_type
    if item.source_url:
        result = await _download(item.source_url)
        if result is not None:
            content, content_type = result
            item.content = content
            item.content_type = content_type or item.content_type
            item.date_updated = utcnow()
            session.add(item)
            session.commit()
            session.refresh(item)
            return content, item.content_type
    return PLACEHOLDER_PNG, "image/png"
