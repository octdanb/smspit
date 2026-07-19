"""GSM-7 / UCS-2 encoding detection and message segment math.

Mirrors carrier behavior (and Twilio's num_segments):
- GSM-7: 160 chars single segment; 153 chars/segment when concatenated (6-byte UDH).
  Characters from the GSM extended table count as 2 (escape + char).
- UCS-2: used when any character is outside GSM-7; 70 single / 67 concatenated,
  counted in UTF-16 code units (astral chars take 2 units).
- Smart Encoding: substitute common Unicode look-alikes with GSM-7 equivalents
  before detection (Twilio's SmartEncoded=true).
"""

from math import ceil

GSM7_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXTENDED = set("^{}\\[~]|€\f")

# Twilio Smart Encoding: map characters that commonly sneak into copy
# (word processors, autocorrect) onto their GSM-7 equivalents.
SMART_ENCODING_MAP = {
    "«": '"',  # «
    "»": '"',  # »
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "„": '"',  # low double quote
    "‘": "'",  # left single quote
    "’": "'",  # right single quote
    "‚": "'",  # low single quote
    "–": "-",  # en dash
    "—": "-",  # em dash
    "―": "-",  # horizontal bar
    "…": "...",  # ellipsis
    " ": " ",  # non-breaking space
    "​": "",  # zero-width space
    "﻿": "",  # BOM / zero-width no-break space
    "•": "*",  # bullet
    "´": "'",  # acute accent
    "`": "'",  # grave accent (GSM-7 lacks backtick)
    "˜": "~",  # small tilde
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    "′": "'",  # prime
    "″": '"',  # double prime
    "‹": "<",  # single left angle quote
    "›": ">",  # single right angle quote
}

GSM7_SINGLE = 160
GSM7_CONCAT = 153
UCS2_SINGLE = 70
UCS2_CONCAT = 67


def apply_smart_encoding(text: str) -> str:
    return "".join(SMART_ENCODING_MAP.get(ch, ch) for ch in text)


def is_gsm7(text: str) -> bool:
    return all(ch in GSM7_BASIC or ch in GSM7_EXTENDED for ch in text)


def gsm7_length(text: str) -> int:
    """Septet count: extended-table characters cost an escape septet + the char."""
    return sum(2 if ch in GSM7_EXTENDED else 1 for ch in text)


def ucs2_length(text: str) -> int:
    """UTF-16 code units (astral characters count as a surrogate pair)."""
    return len(text.encode("utf-16-be")) // 2


def segment_count(text: str, smart_encoded: bool = False) -> tuple[str, int]:
    """Return (encoding, num_segments) for a message body."""
    if smart_encoded:
        text = apply_smart_encoding(text)
    if not text:
        return "gsm7", 1
    if is_gsm7(text):
        length = gsm7_length(text)
        if length <= GSM7_SINGLE:
            return "gsm7", 1
        return "gsm7", ceil(length / GSM7_CONCAT)
    length = ucs2_length(text)
    if length <= UCS2_SINGLE:
        return "ucs2", 1
    return "ucs2", ceil(length / UCS2_CONCAT)
