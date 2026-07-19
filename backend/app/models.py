from datetime import UTC, datetime

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Message(SQLModel, table=True):
    """A captured SMS/MMS message (Twilio Message resource). Initial cut — grows in phase 2."""

    sid: str = Field(primary_key=True)
    account_sid: str
    direction: str  # inbound | outbound-api | outbound-call | outbound-reply
    from_number: str
    to_number: str
    body: str = ""
    status: str = "queued"
    num_segments: int = 1
    num_media: int = 0
    date_created: datetime = Field(default_factory=utcnow)
    date_sent: datetime | None = None
    date_updated: datetime = Field(default_factory=utcnow)
    raw_params: str = "{}"  # JSON of the original request params


class Settings(SQLModel, table=True):
    """Singleton settings row. Initial cut — grows with simulation/strictness options."""

    id: int = Field(default=1, primary_key=True)
    inbound_webhook_url: str | None = None
    inbound_webhook_method: str = "POST"
    account_sid: str = "AC00000000000000000000000000000000"
    auth_token: str = "smspit-auth-token"
