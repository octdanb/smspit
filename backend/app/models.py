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
    # Verify v2 (phase 6): how long a verification code stays valid.
    verify_ttl_seconds: int = 600
    # Lookup v2 (phase 7): JSON dict {E164: line type} overriding the default
    # "mobile" for line_type_intelligence (e.g. {"+15551234567": "nonFixedVoip"}).
    lookup_line_types: str = "{}"
    # Strict mode (phase 8) — everything defaults to permissive.
    strict_auth: bool = False  # Basic creds must match account_sid/auth_token (20003)
    # API key pair also accepted by strict_auth when set (phase 9).
    api_key_sid: str = ""
    api_key_secret: str = ""
    strict_validation: bool = False  # E.164 To/From checks (21211/21212), landline 21614
    trial_mode: bool = False  # sends allowed only to verified_numbers (21608)
    verified_numbers: str = "[]"  # JSON list of E.164 numbers, used by trial_mode
    rate_limit_per_minute: int = 0  # 0 = off; otherwise 429/20429 past the limit
    # Phase 10: dashboard & workflow.
    # JSON list of {"tag": str, "to_suffix"?: str, "from_suffix"?: str, "body_regex"?: str}
    auto_tag_rules: str = "[]"
    retention_max_age_hours: int = 0  # 0 = keep forever
    retention_max_messages: int = 0  # 0 = unlimited


class MessageTag(SQLModel, table=True):
    """A tag on a message (Mailpit-style, for organizing manual testing)."""

    id: int | None = Field(default=None, primary_key=True)
    message_sid: str = Field(index=True)
    tag: str = Field(index=True)


class ThreadRead(SQLModel, table=True):
    """Read-state per thread: messages newer than last_read_at count as unread."""

    number: str = Field(primary_key=True)
    last_read_at: datetime = Field(default_factory=utcnow)


class MessagingService(SQLModel, table=True):
    """Twilio Messaging Service v1 (MG…) with its sender pool in ServiceSender."""

    sid: str = Field(primary_key=True)
    account_sid: str
    friendly_name: str
    inbound_request_url: str | None = None
    inbound_method: str = "POST"
    fallback_url: str | None = None
    fallback_method: str = "POST"
    status_callback: str | None = None
    sticky_sender: bool = True
    smart_encoding: bool = True
    scan_message_content: str = "inherit"  # inherit | enable | disable
    area_code_geomatch: bool = False
    validity_period: int = 36000
    usecase: str = "undeclared"
    use_inbound_webhook_on_number: bool = False
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


class ServiceSender(SQLModel, table=True):
    """A sender pool entry: phone number, alphanumeric sender, or short code."""

    id: int | None = Field(default=None, primary_key=True)
    sid: str = Field(unique=True, index=True)  # PN… | AI… | SC…
    service_sid: str = Field(index=True)
    kind: str  # phone_number | alpha_sender | short_code
    value: str
    country_code: str | None = None
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


class VerifyService(SQLModel, table=True):
    """Twilio Verify v2 Service (VA…)."""

    sid: str = Field(primary_key=True)
    account_sid: str
    friendly_name: str
    code_length: int = 6
    custom_code_enabled: bool = False
    lookup_enabled: bool = False
    skip_sms_to_landlines: bool = False
    dtmf_input_required: bool = False
    tts_name: str | None = None
    psd2_enabled: bool = False
    do_not_share_warning_enabled: bool = False
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


class Verification(SQLModel, table=True):
    """An in-flight Verify v2 verification (VE…)."""

    sid: str = Field(primary_key=True)
    service_sid: str = Field(index=True)
    account_sid: str
    to: str = Field(index=True)
    channel: str = "sms"
    code: str
    status: str = "pending"  # pending | approved | canceled | max_attempts_reached | expired
    check_attempts: int = 0
    send_attempts: str = "[]"  # JSON list of {attempt_sid, channel, time}
    expires_at: datetime
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


class IncomingPhoneNumber(SQLModel, table=True):
    """A provisioned app number (Twilio IncomingPhoneNumber, PN…) with its
    per-number webhook configuration."""

    sid: str = Field(primary_key=True)
    account_sid: str
    phone_number: str = Field(index=True)
    friendly_name: str = ""
    sms_url: str | None = None
    sms_method: str = "POST"
    sms_fallback_url: str | None = None
    sms_fallback_method: str = "POST"
    status_callback: str | None = None
    status_callback_method: str = "POST"
    date_created: datetime = Field(default_factory=utcnow)
    date_updated: datetime = Field(default_factory=utcnow)


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
    method: str = "POST"
    request_params: str = "{}"  # JSON of the form params sent
    response_status: int | None = None
    response_body: str | None = None
    duration_ms: int = 0
    error: str | None = None
    message_sid: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow, index=True)
