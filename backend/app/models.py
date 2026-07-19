import json
from datetime import UTC, datetime

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    # Naive UTC: SQLite has no timezone type, and mixing aware/naive datetimes
    # breaks comparisons. Serializers re-attach UTC on the way out.
    return datetime.now(UTC).replace(tzinfo=None)


DEFAULT_OPTOUT_CONFIG = {
    "keywords": {
        "stop": ["STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE", "OPTOUT"],
        "start": ["START", "YES", "UNSTOP"],
        "help": ["HELP", "INFO"],
    },
    "confirmations": {
        "stop": (
            "You have successfully been unsubscribed. You will not receive any more "
            "messages from this number. Reply START to resubscribe."
        ),
        "start": (
            "You have successfully been re-subscribed to messages from this number. "
            "Reply HELP for help. Reply STOP to unsubscribe."
        ),
        "help": "Reply STOP to unsubscribe. Msg&Data Rates May Apply.",
    },
}


class Message(SQLModel, table=True):
    """A captured SMS/MMS message (Twilio Message resource)."""

    # Autoincrement PK gives a deterministic insertion-order tiebreaker for
    # equal timestamps; sid stays the external (Twilio) identifier.
    id: int | None = Field(default=None, primary_key=True)
    sid: str = Field(unique=True, index=True)
    account_sid: str
    direction: str  # inbound | outbound-api | outbound-call | outbound-reply
    from_number: str = Field(index=True)
    to_number: str = Field(index=True)
    body: str = ""
    status: str = "queued"
    error_code: int | None = None
    error_message: str | None = None
    num_segments: int = 1
    num_media: int = 0
    encoding: str = "gsm7"  # gsm7 | ucs2
    channel: str = "sms"  # sms | mms | whatsapp
    messaging_service_sid: str | None = None
    schedule_type: str | None = None
    send_at: datetime | None = None
    validity_period: int = 36000
    status_callback_url: str | None = None
    price: str | None = None
    provide_feedback: bool = False
    feedback_outcome: str | None = None
    date_created: datetime = Field(default_factory=utcnow, index=True)
    date_sent: datetime | None = None
    date_updated: datetime = Field(default_factory=utcnow)
    raw_params: str = "{}"  # JSON of the original request params


class Settings(SQLModel, table=True):
    """Singleton settings row. Grows with simulation/strictness options."""

    id: int = Field(default=1, primary_key=True)
    inbound_webhook_url: str | None = None
    inbound_webhook_method: str = "POST"
    account_sid: str = "AC00000000000000000000000000000000"
    auth_token: str = "smspit-auth-token"
    # Delivery lifecycle simulation (phase 4).
    simulate_delivery: bool = True
    status_delay_ms: int = 300  # delay between each status transition
    failure_rate: float = 0.0  # 0..1 chance an otherwise-fine message goes undelivered
    # JSON list of {"to_suffix": str, "status": "undelivered"|"failed", "error_code": int}
    forced_rules: str = "[]"
    # Two-way messaging (phase 5).
    public_base_url: str = "http://localhost:8025"  # used for media URLs in webhooks
    enforce_optouts: bool = False  # reject sends to opted-out pairs with error 21610
    # JSON: {"keywords": {"stop": [...], "start": [...], "help": [...]},
    #        "confirmations": {"stop": str, "start": str, "help": str}}
    optout_config: str = Field(default_factory=lambda: json.dumps(DEFAULT_OPTOUT_CONFIG))
    # JSON dict of geo params merged into inbound webhooks (FromCity, FromCountry, ...)
    webhook_geo_params: str = "{}"


class MediaItem(SQLModel, table=True):
    """An MMS attachment (Twilio Media resource). Bytes are fetched lazily."""

    sid: str = Field(primary_key=True)  # ME + 32 hex
    message_sid: str = Field(index=True)
    account_sid: str
    content_type: str = "application/octet-stream"
    source_url: str | None = None  # where the MediaUrl pointed
    content: bytes | None = Field(default=None, sa_column=Column(LargeBinary))
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


class OptOut(SQLModel, table=True):
    """(recipient, sender) opt-out pair. sender '*' applies to all senders."""

    id: int | None = Field(default=None, primary_key=True)
    recipient: str = Field(index=True)  # the number that texted STOP
    sender: str  # the app number it opted out from ('*' = all)
    opted_out: bool = True
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


class WebhookDelivery(SQLModel, table=True):
    """Log of every outbound webhook attempt (status callbacks, inbound messages)."""

    id: int | None = Field(default=None, primary_key=True)
    kind: str  # status_callback | inbound
    url: str
    request_params: str = "{}"  # JSON of the form params sent
    response_status: int | None = None
    response_body: str | None = None
    duration_ms: int = 0
    error: str | None = None
    message_sid: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
