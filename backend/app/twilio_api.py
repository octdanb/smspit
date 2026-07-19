"""Twilio Programmable Messaging API emulation (2010-04-01): Messages resource."""

import json
import re
import secrets
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from urllib.parse import urlencode

import phonenumbers
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlmodel import Session, col, func, select

from . import lifecycle, media, optout
from .db import get_session, get_settings
from .errors import TwilioError, auth_error, not_found
from .internal_api import counterparty, message_to_internal
from .models import IncomingPhoneNumber, MediaItem, Message, MessagingService, utcnow
from .segments import segment_count
from .ws import manager

router = APIRouter()

API_VERSION = "2010-04-01"
PRICE_PER_SEGMENT = 0.0075

_basic = HTTPBasic(auto_error=False)


def require_basic_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    session: Session = Depends(get_session),
) -> HTTPBasicCredentials:
    """HTTP Basic: permissive by default (any non-empty credentials); with
    strict_auth on, credentials must match the configured account SID + token."""
    if credentials is None or not credentials.username:
        raise auth_error()
    settings = get_settings(session)
    if settings.strict_auth:
        account_ok = (
            credentials.username == settings.account_sid
            and credentials.password == settings.auth_token
        )
        api_key_ok = bool(settings.api_key_sid) and (
            credentials.username == settings.api_key_sid
            and credentials.password == settings.api_key_secret
        )
        if not (account_ok or api_key_ok):
            raise TwilioError(20003, "Authentication Error - invalid credentials", 401)
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


ALPHA_SENDER = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9 _&+-]{1,11}$")
SHORT_CODE = re.compile(r"^\d{5,6}$")


def _strip_channel(number: str) -> str:
    return number.removeprefix("whatsapp:")


def is_valid_e164(number: str) -> bool:
    # is_possible_number (structure/length), not is_valid_number: dev tools are
    # fed fictional 555 numbers all day, and Twilio-grade carrier validation
    # would reject them. Lookup v2 keeps full validity checking.
    try:
        return phonenumbers.is_possible_number(phonenumbers.parse(_strip_channel(number)))
    except phonenumbers.NumberParseException:
        return False


def is_valid_sender(sender: str) -> bool:
    bare = _strip_channel(sender)
    return is_valid_e164(bare) or bool(SHORT_CODE.match(bare)) or bool(ALPHA_SENDER.match(bare))


def _number_status_callback(session: Session, from_: str) -> str | None:
    """Callback precedence tail: the sending number's configured StatusCallback."""
    if not from_:
        return None
    number = session.exec(
        select(IncomingPhoneNumber).where(IncomingPhoneNumber.phone_number == from_)
    ).first()
    return number.status_callback if number is not None else None


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

    service: MessagingService | None = None
    if messaging_service_sid:
        service = session.get(MessagingService, messaging_service_sid)
        if service is None:
            raise TwilioError(21701, "The Messaging Service was not found.", http_status=404)

    content_sid = single.get("ContentSid", "").strip() or None
    if not body and not media_urls and not content_sid:
        raise TwilioError(21602, "Message body or media urls are required.")
    if not body and content_sid:
        # No template store in the mock: render the variables as plain text so
        # the message is inspectable in the dashboard and by latest-code.
        try:
            variables = json.loads(single.get("ContentVariables") or "{}")
        except ValueError:
            variables = {}
        rendered = ", ".join(f"{key}: {value}" for key, value in variables.items())
        body = f"[{content_sid}]" + (f" {rendered}" if rendered else "")
    if len(body) > 1600:
        raise TwilioError(21617, "The concatenated message body exceeds the 1600 character limit.")

    settings = get_settings(session)
    if settings.strict_validation:
        if not is_valid_e164(to):
            raise TwilioError(21211, f"The 'To' number {to} is not a valid phone number.")
        if from_ and not is_valid_sender(from_):
            raise TwilioError(21212, f"The 'From' number {from_} is not a valid phone number.")
        line_types = json.loads(settings.lookup_line_types or "{}")
        if line_types.get(_strip_channel(to)) == "landline":
            raise TwilioError(21614, f"'To' number {to} is not a valid mobile number.")
        if to.startswith("whatsapp:") and not content_sid:
            # WhatsApp 24h session window: free-form sends need a recent
            # inbound message from this user; template sends always pass.
            window_start = utcnow() - timedelta(hours=24)
            recent_inbound = session.exec(
                select(Message)
                .where(
                    Message.direction == "inbound",
                    Message.from_number == to,
                    col(Message.date_created) >= window_start,
                )
                .limit(1)
            ).first()
            if recent_inbound is None:
                raise TwilioError(
                    63016,
                    "Failed to send freeform message because you are outside the allowed "
                    "window. Please use a Message Template (ContentSid).",
                )
    if settings.trial_mode:
        verified = json.loads(settings.verified_numbers or "[]")
        if to not in verified:
            raise TwilioError(
                21608,
                f"The number {to} is unverified. Trial accounts may only send to verified numbers.",
            )
    if settings.rate_limit_per_minute > 0:
        window_start = utcnow() - timedelta(seconds=60)
        recent = session.exec(
            select(func.count())
            .select_from(Message)
            .where(
                col(Message.direction).startswith("outbound"),
                col(Message.date_created) >= window_start,
            )
        ).one()
        if recent >= settings.rate_limit_per_minute:
            raise TwilioError(20429, "Too Many Requests", http_status=429)
    if from_ and settings.enforce_optouts and optout.is_opted_out(session, to, from_):
        raise TwilioError(21610, "Attempt to send to unsubscribed recipient")

    smart_encoded = parse_bool(single.get("SmartEncoded")) or (
        service is not None and service.smart_encoding and "SmartEncoded" not in single
    )
    encoding, num_segments = segment_count(body, smart_encoded=smart_encoded)

    schedule_type = single.get("ScheduleType") or None
    send_at = None
    # Service sends start as 'accepted' while the pool picks a From (lifecycle).
    status = "accepted" if (service is not None and not from_) else "queued"
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
        validity_period=int(
            single.get("ValidityPeriod")
            or (service.validity_period if service is not None else 36000)
        ),
        status_callback_url=single.get("StatusCallback")
        or (service.status_callback if service is not None else None)
        or _number_status_callback(session, from_),
        provide_feedback=parse_bool(single.get("ProvideFeedback")),
        raw_params=json.dumps(
            {key: values if len(values) > 1 else values[0] for key, values in params.items()}
        ),
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    media.create_media_items(session, message.sid, account_sid, media_urls)

    await manager.broadcast(
        "message.created",
        {"number": counterparty(message), "message": message_to_internal(session, message)},
    )
    if settings.simulate_delivery:
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
        {"number": counterparty(message), "message": message_to_internal(session, message)},
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
    for item in media.media_for_message(session, sid):
        session.delete(item)
    session.delete(message)
    session.commit()
    await manager.broadcast("messages.cleared", {"number": number})


@router.post("/2010-04-01/Accounts/{account_sid}/Messages/{sid}/Feedback.json", status_code=201)
async def create_feedback(
    account_sid: str,
    sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    """Message Feedback: only for messages sent with ProvideFeedback=true."""
    message = session.exec(select(Message).where(Message.sid == sid)).first()
    if message is None:
        raise not_found(f"2010-04-01/Accounts/{account_sid}/Messages/{sid}/Feedback.json")
    if not message.provide_feedback:
        raise TwilioError(
            20001, "Feedback is only available for messages sent with ProvideFeedback=true."
        )
    form = await request.form()
    outcome = str(form.get("Outcome") or "confirmed")
    if outcome not in ("confirmed", "unconfirmed"):
        raise TwilioError(20001, "Outcome must be 'confirmed' or 'unconfirmed'.")

    message.feedback_outcome = outcome
    message.date_updated = utcnow()
    session.add(message)
    session.commit()
    session.refresh(message)
    now = rfc2822(utcnow())
    return {
        "account_sid": message.account_sid,
        "message_sid": message.sid,
        "outcome": outcome,
        "date_created": now,
        "date_updated": now,
        "uri": f"/2010-04-01/Accounts/{message.account_sid}/Messages/{message.sid}/Feedback.json",
    }


def media_to_json(item: MediaItem) -> dict:
    base = f"/2010-04-01/Accounts/{item.account_sid}/Messages/{item.message_sid}/Media/{item.sid}"
    return {
        "sid": item.sid,
        "account_sid": item.account_sid,
        "parent_sid": item.message_sid,
        "content_type": item.content_type,
        "date_created": rfc2822(item.date_created),
        "date_updated": rfc2822(item.date_updated),
        "uri": f"{base}.json",
    }


@router.get("/2010-04-01/Accounts/{account_sid}/Messages/{message_sid}/Media.json")
def list_media(
    account_sid: str,
    message_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    query = request.query_params
    items = media.media_for_message(session, message_sid)
    if query.get("DateCreated"):
        day = parse_filter_dt(query["DateCreated"])
        items = [i for i in items if day <= i.date_created < day + timedelta(days=1)]
    if query.get("DateCreated<"):
        limit_dt = parse_filter_dt(query["DateCreated<"])
        items = [i for i in items if i.date_created <= limit_dt]
    if query.get("DateCreated>"):
        limit_dt = parse_filter_dt(query["DateCreated>"])
        items = [i for i in items if i.date_created >= limit_dt]

    page_size = min(int(query.get("PageSize") or 50), 1000)
    page = int(query.get("Page") or 0)
    start = page * page_size
    chunk = items[start : start + page_size]
    has_more = len(items) > start + page_size

    path = f"/2010-04-01/Accounts/{account_sid}/Messages/{message_sid}/Media.json"
    return {
        "media_list": [media_to_json(item) for item in chunk],
        "page": page,
        "page_size": page_size,
        "first_page_uri": f"{path}?PageSize={page_size}&Page=0",
        "previous_page_uri": f"{path}?PageSize={page_size}&Page={page - 1}" if page > 0 else None,
        "next_page_uri": f"{path}?PageSize={page_size}&Page={page + 1}" if has_more else None,
        "uri": str(request.url.path),
        "start": start,
        "end": start + max(len(chunk) - 1, 0),
    }


def _get_media_item(session: Session, account_sid: str, media_sid: str) -> MediaItem:
    item = session.get(MediaItem, media_sid)
    if item is None:
        raise not_found(f"2010-04-01/Accounts/{account_sid}/Media/{media_sid}")
    return item


@router.get("/2010-04-01/Accounts/{account_sid}/Messages/{message_sid}/Media/{media_sid}.json")
def fetch_media(
    account_sid: str,
    message_sid: str,
    media_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return media_to_json(_get_media_item(session, account_sid, media_sid))


@router.get("/2010-04-01/Accounts/{account_sid}/Messages/{message_sid}/Media/{media_sid}")
def fetch_media_content(
    account_sid: str,
    message_sid: str,
    media_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> RedirectResponse:
    """Twilio redirects the extensionless media URL to the stored bytes."""
    _get_media_item(session, account_sid, media_sid)
    base = get_settings(session).public_base_url.rstrip("/")
    return RedirectResponse(f"{base}/api/media/{media_sid}", status_code=302)


@router.delete(
    "/2010-04-01/Accounts/{account_sid}/Messages/{message_sid}/Media/{media_sid}.json",
    status_code=204,
)
def delete_media(
    account_sid: str,
    message_sid: str,
    media_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    item = _get_media_item(session, account_sid, media_sid)
    message = session.exec(select(Message).where(Message.sid == item.message_sid)).first()
    session.delete(item)
    if message is not None:
        message.num_media = max(message.num_media - 1, 0)
        message.date_updated = utcnow()
        session.add(message)
    session.commit()
