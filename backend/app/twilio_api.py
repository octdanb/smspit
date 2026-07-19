"""Twilio Programmable Messaging API emulation (2010-04-01): Messages resource."""

import json
import secrets
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session, col, select

from . import lifecycle
from .db import get_session, get_settings
from .errors import TwilioError, auth_error, not_found
from .internal_api import counterparty, message_to_internal
from .models import Message, utcnow
from .segments import segment_count
from .ws import manager

router = APIRouter()

API_VERSION = "2010-04-01"
PRICE_PER_SEGMENT = 0.0075

_basic = HTTPBasic(auto_error=False)


def require_basic_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
) -> HTTPBasicCredentials:
    """Permissive HTTP Basic: any non-empty credentials pass (strict mode lands later)."""
    if credentials is None or not credentials.username:
        raise auth_error()
    return credentials


def new_sid(prefix: str) -> str:
    return prefix + secrets.token_hex(16)


def rfc2822(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return format_datetime(dt.astimezone(UTC))


def message_to_json(message: Message) -> dict:
    base_uri = f"/2010-04-01/Accounts/{message.account_sid}/Messages/{message.sid}"
    return {
        "sid": message.sid,
        "account_sid": message.account_sid,
        "api_version": API_VERSION,
        "body": message.body,
        "num_segments": str(message.num_segments),
        "num_media": str(message.num_media),
        "direction": message.direction,
        "from": message.from_number,
        "to": message.to_number,
        "date_created": rfc2822(message.date_created),
        "date_sent": rfc2822(message.date_sent),
        "date_updated": rfc2822(message.date_updated),
        "price": message.price,
        "price_unit": "USD",
        "error_code": message.error_code,
        "error_message": message.error_message,
        "status": message.status,
        "messaging_service_sid": message.messaging_service_sid,
        "uri": f"{base_uri}.json",
        "subresource_uris": {
            "media": f"{base_uri}/Media.json",
            "feedback": f"{base_uri}/Feedback.json",
        },
    }


def parse_bool(value: str | None) -> bool:
    return (value or "").lower() == "true"


def parse_filter_dt(value: str) -> datetime:
    """Parse a DateSent filter (YYYY-MM-DD or ISO 8601) to naive UTC."""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TwilioError(20001, f"Invalid DateSent value: {value}") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


@router.post("/2010-04-01/Accounts/{account_sid}/Messages.json", status_code=201)
async def create_message(
    account_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    params = {key: form.getlist(key) for key in form}
    single = {key: values[-1] for key, values in params.items()}

    to = single.get("To", "").strip()
    from_ = single.get("From", "").strip()
    messaging_service_sid = single.get("MessagingServiceSid", "").strip() or None
    body = single.get("Body", "")
    media_urls = [url for url in params.get("MediaUrl", []) if url]

    if not to:
        raise TwilioError(21604, "A 'To' phone number is required.")
    if not from_ and not messaging_service_sid:
        raise TwilioError(21603, "A 'From' phone number is required.")
    if not from_:
        # Messaging Service sender pools land in phase 7.
        raise TwilioError(
            21606,
            "The From phone number provided is not a valid, message-capable phone number.",
        )
    if not body and not media_urls and not single.get("ContentSid"):
        raise TwilioError(21602, "Message body or media urls are required.")
    if len(body) > 1600:
        raise TwilioError(21617, "The concatenated message body exceeds the 1600 character limit.")

    smart_encoded = parse_bool(single.get("SmartEncoded"))
    encoding, num_segments = segment_count(body, smart_encoded=smart_encoded)

    schedule_type = single.get("ScheduleType") or None
    send_at = None
    status = "queued"
    if schedule_type is not None:
        if schedule_type != "fixed":
            raise TwilioError(20001, "ScheduleType must be 'fixed'.")
        if not single.get("SendAt"):
            raise TwilioError(20001, "SendAt is required when ScheduleType is provided.")
        send_at = parse_filter_dt(single["SendAt"])
        status = "scheduled"

    is_mms = bool(media_urls) or parse_bool(single.get("SendAsMms"))
    channel = "whatsapp" if to.startswith("whatsapp:") else ("mms" if is_mms else "sms")

    message = Message(
        sid=new_sid("MM" if is_mms else "SM"),
        account_sid=account_sid,
        direction="outbound-api",
        from_number=from_,
        to_number=to,
        body=body,
        status=status,
        schedule_type=schedule_type,
        send_at=send_at,
        num_segments=num_segments,
        num_media=len(media_urls),
        encoding=encoding,
        channel=channel,
        messaging_service_sid=messaging_service_sid,
        validity_period=int(single.get("ValidityPeriod") or 36000),
        status_callback_url=single.get("StatusCallback") or None,
        provide_feedback=parse_bool(single.get("ProvideFeedback")),
        raw_params=json.dumps(
            {key: values if len(values) > 1 else values[0] for key, values in params.items()}
        ),
    )
    session.add(message)
    session.commit()
    session.refresh(message)

    await manager.broadcast(
        "message.created",
        {"number": counterparty(message), "message": message_to_internal(message)},
    )
    if get_settings(session).simulate_delivery:
        lifecycle.start(message.sid)
    return message_to_json(message)


@router.get("/2010-04-01/Accounts/{account_sid}/Messages.json")
def list_messages(
    account_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    query = request.query_params
    page_size = min(int(query.get("PageSize") or 50), 1000)
    page = int(query.get("Page") or 0)
    page_token = query.get("PageToken")

    stmt = select(Message).order_by(col(Message.date_created).desc(), col(Message.id).desc())
    if query.get("To"):
        stmt = stmt.where(Message.to_number == query["To"])
    if query.get("From"):
        stmt = stmt.where(Message.from_number == query["From"])
    if query.get("DateSent"):
        day = parse_filter_dt(query["DateSent"])
        stmt = stmt.where(col(Message.date_created) >= day)
        if len(query["DateSent"]) == 10:  # date-only: match the whole day
            stmt = stmt.where(col(Message.date_created) < day + timedelta(days=1))
    if query.get("DateSent<"):
        stmt = stmt.where(col(Message.date_created) <= parse_filter_dt(query["DateSent<"]))
    if query.get("DateSent>"):
        stmt = stmt.where(col(Message.date_created) >= parse_filter_dt(query["DateSent>"]))

    if page_token:
        # Relative paging: token is the last sid of the previous page.
        anchor = session.exec(
            select(Message).where(Message.sid == page_token.removeprefix("PA"))
        ).first()
        if anchor is not None:
            stmt = stmt.where(
                (col(Message.date_created) < anchor.date_created)
                | (
                    (col(Message.date_created) == anchor.date_created)
                    & (col(Message.id) < anchor.id)
                )
            )
        records = session.exec(stmt.limit(page_size + 1)).all()
    else:
        records = session.exec(stmt.offset(page * page_size).limit(page_size + 1)).all()

    has_more = len(records) > page_size
    records = records[:page_size]

    path = f"/2010-04-01/Accounts/{account_sid}/Messages.json"
    filter_keys = ("To", "From", "DateSent", "DateSent<", "DateSent>")
    filters = {key: query[key] for key in filter_keys if query.get(key)}

    def page_uri(page_num: int, token: str | None = None) -> str:
        q = dict(filters)
        q["PageSize"] = str(page_size)
        q["Page"] = str(page_num)
        if token:
            q["PageToken"] = token
        return f"{path}?{urlencode(q)}"

    next_page_uri = None
    if has_more and records:
        next_page_uri = page_uri(page + 1, token=f"PA{records[-1].sid}")

    return {
        "messages": [message_to_json(m) for m in records],
        "page": page,
        "page_size": page_size,
        "first_page_uri": page_uri(0),
        "previous_page_uri": None,
        "next_page_uri": next_page_uri,
        "uri": str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
        "start": page * page_size,
        "end": page * page_size + max(len(records) - 1, 0),
    }


@router.get("/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json")
def fetch_message(
    account_sid: str,
    sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise not_found(f"2010-04-01/Accounts/{account_sid}/Messages/{sid}.json")
    return message_to_json(message)


@router.post("/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json")
async def update_message(
    account_sid: str,
    sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    """Twilio message updates: Body="" redacts; Status=canceled cancels a scheduled send."""
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise not_found(f"2010-04-01/Accounts/{account_sid}/Messages/{sid}.json")

    form = await request.form()
    if "Status" in form:
        if str(form["Status"]).lower() != "canceled":
            raise TwilioError(20001, "Status can only be updated to 'canceled'.")
        if message.status != "scheduled":
            raise TwilioError(20001, "Only messages with status 'scheduled' can be canceled.")
        message.status = "canceled"
    elif "Body" in form:
        if form["Body"] != "":
            raise TwilioError(
                20001, "Body can only be updated to an empty string (message redaction)."
            )
        message.body = ""
    else:
        raise TwilioError(20001, "No updatable parameter provided (Body or Status).")

    message.date_updated = utcnow()
    session.add(message)
    session.commit()
    session.refresh(message)

    await manager.broadcast(
        "message.status_changed",
        {"number": counterparty(message), "message": message_to_internal(message)},
    )
    return message_to_json(message)


@router.delete("/2010-04-01/Accounts/{account_sid}/Messages/{sid}.json", status_code=204)
async def delete_message(
    account_sid: str,
    sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise not_found(f"2010-04-01/Accounts/{account_sid}/Messages/{sid}.json")
    if message.status not in lifecycle.TERMINAL_STATUSES:
        raise TwilioError(
            20009, "Cannot delete this resource before it is complete", http_status=409
        )
    number = counterparty(message)
    session.delete(message)
    session.commit()
    await manager.broadcast("messages.cleared", {"number": number})
