"""TwiML response parsing for inbound-message webhooks.

When the app's webhook answers with <Response><Message>...</Message></Response>,
Twilio sends the reply back to the user. The mock does the same: each parsed
Message becomes an outbound message in the thread.
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class TwimlMessage:
    body: str = ""
    to: str | None = None
    from_: str | None = None
    media: list[str] = field(default_factory=list)


@dataclass
class TwimlResult:
    messages: list[TwimlMessage] = field(default_factory=list)
    redirect_url: str | None = None


def looks_like_twiml(content_type: str, body: str) -> bool:
    if "xml" in (content_type or "").lower():
        return True
    stripped = body.lstrip()
    return stripped.startswith("<?xml") or stripped.startswith("<Response")


def parse_twiml(xml_text: str) -> TwimlResult:
    """Parse a TwiML <Response>. Raises ValueError on malformed XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid TwiML: {exc}") from exc
    if root.tag != "Response":
        raise ValueError(f"Expected <Response> root, got <{root.tag}>")

    result = TwimlResult()
    for element in root:
        if element.tag == "Message":
            message = TwimlMessage(
                to=element.get("to"),
                from_=element.get("from"),
            )
            body_el = element.find("Body")
            if body_el is not None:
                message.body = (body_el.text or "").strip()
            else:
                message.body = (element.text or "").strip()
            for media_el in element.findall("Media"):
                if media_el.text and media_el.text.strip():
                    message.media.append(media_el.text.strip())
            result.messages.append(message)
        elif element.tag == "Redirect":
            if element.text and element.text.strip():
                result.redirect_url = element.text.strip()
    return result
