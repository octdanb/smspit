"""Twilio Messaging Services v1 emulation: /v1/Services + sender pools."""

import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPBasicCredentials
from sqlmodel import Session, col, select

from .db import get_session, get_settings
from .errors import TwilioError, not_found
from .models import MessagingService, ServiceSender, utcnow
from .pagination import meta_page
from .twilio_api import parse_bool, require_basic_auth

router = APIRouter(prefix="/v1/Services")

ALPHA_SENDER = re.compile(r"^(?=.*[A-Za-z])[A-Za-z0-9 _&+-]{1,11}$")
SHORT_CODE = re.compile(r"^\d{5,6}$")

SENDER_KINDS = {
    "phone_number": {"prefix": "PN", "key": "phone_numbers", "path": "PhoneNumbers"},
    "alpha_sender": {"prefix": "AI", "key": "alpha_senders", "path": "AlphaSenders"},
    "short_code": {"prefix": "SC", "key": "short_codes", "path": "ShortCodes"},
}


def iso(dt: datetime) -> str:
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def service_to_json(service: MessagingService) -> dict:
    base = f"/v1/Services/{service.sid}"
    return {
        "sid": service.sid,
        "account_sid": service.account_sid,
        "friendly_name": service.friendly_name,
        "inbound_request_url": service.inbound_request_url,
        "inbound_method": service.inbound_method,
        "fallback_url": service.fallback_url,
        "fallback_method": service.fallback_method,
        "status_callback": service.status_callback,
        "sticky_sender": service.sticky_sender,
        "smart_encoding": service.smart_encoding,
        "scan_message_content": service.scan_message_content,
        "area_code_geomatch": service.area_code_geomatch,
        "validity_period": service.validity_period,
        "usecase": service.usecase,
        "use_inbound_webhook_on_number": service.use_inbound_webhook_on_number,
        "us_app_to_person_registered": False,
        "date_created": iso(service.date_created),
        "date_updated": iso(service.date_updated),
        "url": base,
        "links": {
            "phone_numbers": f"{base}/PhoneNumbers",
            "alpha_senders": f"{base}/AlphaSenders",
            "short_codes": f"{base}/ShortCodes",
        },
    }


def sender_to_json(sender: ServiceSender) -> dict:
    kind = SENDER_KINDS[sender.kind]
    data = {
        "sid": sender.sid,
        "account_sid": "",  # filled by caller
        "service_sid": sender.service_sid,
        "date_created": iso(sender.date_created),
        "date_updated": iso(sender.date_updated),
        "url": f"/v1/Services/{sender.service_sid}/{kind['path']}/{sender.sid}",
    }
    if sender.kind == "phone_number":
        data["phone_number"] = sender.value
        data["country_code"] = sender.country_code
        data["capabilities"] = ["SMS", "MMS"]
    elif sender.kind == "alpha_sender":
        data["alpha_sender"] = sender.value
        data["capabilities"] = ["SMS"]
    else:
        data["short_code"] = sender.value
        data["capabilities"] = ["SMS"]
    return data


def _get_service(session: Session, sid: str) -> MessagingService:
    service = session.get(MessagingService, sid)
    if service is None:
        raise not_found(f"v1/Services/{sid}")
    return service


def _apply_service_params(service: MessagingService, form) -> None:
    if form.get("FriendlyName"):
        name = str(form["FriendlyName"])
        if len(name) > 64:
            raise TwilioError(21650, "FriendlyName must be 64 characters or fewer.")
        service.friendly_name = name
    for param, attr in (
        ("InboundRequestUrl", "inbound_request_url"),
        ("FallbackUrl", "fallback_url"),
        ("StatusCallback", "status_callback"),
    ):
        if param in form:
            setattr(service, attr, str(form[param]) or None)
    for param, attr in (
        ("InboundMethod", "inbound_method"),
        ("FallbackMethod", "fallback_method"),
        ("Usecase", "usecase"),
    ):
        if form.get(param):
            setattr(service, attr, str(form[param]))
    if form.get("ScanMessageContent"):
        value = str(form["ScanMessageContent"])
        if value not in ("inherit", "enable", "disable"):
            raise TwilioError(20001, "ScanMessageContent must be inherit, enable, or disable.")
        service.scan_message_content = value
    if form.get("ValidityPeriod"):
        period = int(form["ValidityPeriod"])
        if not 1 <= period <= 36000:
            raise TwilioError(20001, "ValidityPeriod must be between 1 and 36000.")
        service.validity_period = period
    for param, attr in (
        ("StickySender", "sticky_sender"),
        ("SmartEncoding", "smart_encoding"),
        ("AreaCodeGeomatch", "area_code_geomatch"),
        ("UseInboundWebhookOnNumber", "use_inbound_webhook_on_number"),
    ):
        if param in form:
            setattr(service, attr, parse_bool(str(form[param])))
    # Obsolete Twilio params, accepted and ignored:
    # MmsConverter, FallbackToLongCode, SynchronousValidation.


@router.post("", status_code=201)
@router.post("/", status_code=201, include_in_schema=False)
async def create_service(
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    if not form.get("FriendlyName"):
        raise TwilioError(21650, "FriendlyName is required.")
    service = MessagingService(
        sid="MG" + secrets.token_hex(16),
        account_sid=get_settings(session).account_sid,
        friendly_name="",
    )
    _apply_service_params(service, form)
    session.add(service)
    session.commit()
    session.refresh(service)
    return service_to_json(service)


@router.get("")
@router.get("/", include_in_schema=False)
def list_services(
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    services = session.exec(select(MessagingService).order_by(col(MessagingService.sid))).all()
    return meta_page(request, [service_to_json(s) for s in services], "services", "/v1/Services")


@router.get("/{service_sid}")
def fetch_service(
    service_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return service_to_json(_get_service(session, service_sid))


@router.post("/{service_sid}")
async def update_service(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    service = _get_service(session, service_sid)
    _apply_service_params(service, await request.form())
    service.date_updated = utcnow()
    session.add(service)
    session.commit()
    session.refresh(service)
    return service_to_json(service)


@router.delete("/{service_sid}", status_code=204)
def delete_service(
    service_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    service = _get_service(session, service_sid)
    for sender in session.exec(
        select(ServiceSender).where(ServiceSender.service_sid == service_sid)
    ).all():
        session.delete(sender)
    session.delete(service)
    session.commit()


def pool_for(session: Session, service_sid: str) -> list[ServiceSender]:
    return list(
        session.exec(
            select(ServiceSender)
            .where(ServiceSender.service_sid == service_sid)
            .order_by(col(ServiceSender.id))
        ).all()
    )


def _account_sid(session: Session) -> str:
    return get_settings(session).account_sid


def _add_sender(session: Session, service_sid: str, kind: str, value: str) -> dict:
    _get_service(session, service_sid)
    sender = ServiceSender(
        sid=SENDER_KINDS[kind]["prefix"] + secrets.token_hex(16),
        service_sid=service_sid,
        kind=kind,
        value=value,
        country_code="US" if kind == "phone_number" and value.startswith("+1") else None,
    )
    session.add(sender)
    session.commit()
    session.refresh(sender)
    data = sender_to_json(sender)
    data["account_sid"] = _account_sid(session)
    return data


def _list_senders(request: Request, session: Session, service_sid: str, kind: str) -> dict:
    _get_service(session, service_sid)
    senders = [s for s in pool_for(session, service_sid) if s.kind == kind]
    account_sid = _account_sid(session)
    items = []
    for sender in senders:
        data = sender_to_json(sender)
        data["account_sid"] = account_sid
        items.append(data)
    meta_key = SENDER_KINDS[kind]["key"]
    path = f"/v1/Services/{service_sid}/{SENDER_KINDS[kind]['path']}"
    return meta_page(request, items, meta_key, path)


def _delete_sender(session: Session, service_sid: str, sender_sid: str) -> None:
    sender = session.exec(select(ServiceSender).where(ServiceSender.sid == sender_sid)).first()
    if sender is None or sender.service_sid != service_sid:
        raise not_found(f"v1/Services/{service_sid}/…/{sender_sid}")
    session.delete(sender)
    session.commit()


@router.post("/{service_sid}/PhoneNumbers", status_code=201)
async def add_phone_number(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    # Real Twilio takes PhoneNumberSid (an IncomingPhoneNumber PN sid); the
    # mock has no number inventory, so it also accepts a raw PhoneNumber.
    number = str(form.get("PhoneNumber") or form.get("PhoneNumberSid") or "").strip()
    if not number.startswith("+"):
        raise TwilioError(21606, "Provide PhoneNumber in E.164 format (mock accepts either).")
    return _add_sender(session, service_sid, "phone_number", number)


@router.get("/{service_sid}/PhoneNumbers")
def list_phone_numbers(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return _list_senders(request, session, service_sid, "phone_number")


@router.delete("/{service_sid}/PhoneNumbers/{sender_sid}", status_code=204)
def delete_phone_number(
    service_sid: str,
    sender_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    _delete_sender(session, service_sid, sender_sid)


@router.post("/{service_sid}/AlphaSenders", status_code=201)
async def add_alpha_sender(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    value = str(form.get("AlphaSender") or "").strip()
    if not ALPHA_SENDER.match(value):
        raise TwilioError(
            21709,
            "AlphaSender must be 1-11 characters from A-Z a-z 0-9 space _&+- with a letter.",
        )
    return _add_sender(session, service_sid, "alpha_sender", value)


@router.get("/{service_sid}/AlphaSenders")
def list_alpha_senders(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return _list_senders(request, session, service_sid, "alpha_sender")


@router.delete("/{service_sid}/AlphaSenders/{sender_sid}", status_code=204)
def delete_alpha_sender(
    service_sid: str,
    sender_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    _delete_sender(session, service_sid, sender_sid)


@router.post("/{service_sid}/ShortCodes", status_code=201)
async def add_short_code(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    form = await request.form()
    value = str(form.get("ShortCode") or form.get("ShortCodeSid") or "").strip()
    if not SHORT_CODE.match(value):
        raise TwilioError(20001, "ShortCode must be 5-6 digits (mock accepts the code itself).")
    return _add_sender(session, service_sid, "short_code", value)


@router.get("/{service_sid}/ShortCodes")
def list_short_codes(
    service_sid: str,
    request: Request,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> dict:
    return _list_senders(request, session, service_sid, "short_code")


@router.delete("/{service_sid}/ShortCodes/{sender_sid}", status_code=204)
def delete_short_code(
    service_sid: str,
    sender_sid: str,
    session: Session = Depends(get_session),
    _auth: HTTPBasicCredentials = Depends(require_basic_auth),
) -> None:
    _delete_sender(session, service_sid, sender_sid)


def select_sender(session: Session, service: MessagingService, to: str) -> str | None:
    """Pick a From for a message sent via this service (sticky > geomatch > first)."""
    pool = pool_for(session, service.sid)
    if not pool:
        return None
    values = [sender.value for sender in pool]

    if service.sticky_sender:
        from .models import Message

        previous = session.exec(
            select(Message)
            .where(
                Message.messaging_service_sid == service.sid,
                Message.to_number == to,
                Message.from_number != "",  # noqa: PLC1901
                col(Message.direction).startswith("outbound"),
            )
            .order_by(col(Message.id).desc())
        ).first()
        if previous is not None and previous.from_number in values:
            return previous.from_number

    if service.area_code_geomatch and to.startswith("+1") and len(to) == 12:
        area = to[2:5]
        for value in values:
            if value.startswith(f"+1{area}"):
                return value

    return values[0]
